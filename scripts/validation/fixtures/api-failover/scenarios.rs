#[cfg(test)]
mod scenarios {
    use super::*;
    use serde_json::Value;
    fn reset() {
        let mut s = state().lock().unwrap();
        s.phase = Phase::Primary;
        s.retry_at = None;
        s.generation += 1;
    }
    fn pair() -> (Url, Url) {
        (Url::parse(&std::env::var("API_TEST_PRIMARY").unwrap()).unwrap(),
         Url::parse(&std::env::var("API_TEST_FALLBACK").unwrap()).unwrap())
    }
    fn expire() { state().lock().unwrap().retry_at = Some(Instant::now() - Duration::from_secs(1)); }
    async fn request(p: (Url, Url), path: &str, method: Method) -> Result<Response, String> {
        let u = p.0.join(path).unwrap().to_string();
        let mut h = HeaderMap::new();
        h.insert("Authorization", "Bearer fixture-only".parse().unwrap());
        send_for(p, &u, method, h, Some("fixture-body".to_owned())).await
    }
    async fn stats(u: &Url) -> Value {
        Client::builder().no_proxy().use_rustls_tls().build().unwrap()
            .get(u.join("/stats").unwrap()).send().await.unwrap().json().await.unwrap()
    }
    #[test]
    fn origins_and_scope() {
        for u in ["http://localhost", "https://user:pass@localhost", "https://localhost/api/", "https://localhost?q=x", "https://localhost/#x"] {
            assert!(origin(u).is_none(), "{u}");
        }
        assert!(handles("https://api.test.invalid/api/login"));
        for u in ["https://elsewhere.invalid/api/login", "https://api.test.invalid.evil.invalid/api/login", "http://api.test.invalid/api/login", "https://user@api.test.invalid/api/login", "https://api.test.invalid/download"] {
            assert!(!handles(u));
        }
        assert_eq!(origin("https://[0:0:0:0:0:0:0:1]").unwrap().origin(), origin("https://[::1]").unwrap().origin());
        let rewritten = rewrite("https://api.test.invalid/api/devices?page=2", &origin("https://backup.test.invalid").unwrap()).unwrap();
        assert_eq!(rewritten.as_str(), "https://backup.test.invalid/api/devices?page=2");
    }
    // One sequential scenario protects the process-local selector from test races.
    #[tokio::test]
    async fn transport_and_recovery() {
        use hbb_common::radar_diagnostics as diagnostics;
        let root = std::path::PathBuf::from(std::env::var("SSL_CERT_FILE").unwrap());
        diagnostics::initialize(root.parent().unwrap().join("diagnostic-test")).unwrap();
        let engine = diagnostics::global().unwrap();
        engine.request(serde_json::json!({"op":"start","settings":diagnostics::Settings {enabled:true,..Default::default()}})).unwrap();
        reset();
        let p = pair();
        let response = request(p.clone(), "/api/status/200#rd-api-request-local", Method::POST).await.unwrap();
        assert!(response.remote_addr().unwrap().is_ipv6());
        let body: Value = response.json().await.unwrap();
        assert_eq!(body["authorization"], "Bearer fixture-only");
        assert_eq!(body["body"], "fixture-body");
        assert_eq!(body["path"], "/api/status/200", "private polling fragment must not be transmitted");
        assert_eq!(body["host"], format!("localhost:{}", p.0.port().unwrap()));
        // Accepted IPv6-literal policies bypass DNS, preserve IP certificate
        // validation, and recover to the literal primary after cooldown.
        reset();
        let literal = Url::parse(&format!("https://[::1]:{}", p.0.port().unwrap())).unwrap();
        let response = request((literal.clone(), p.1.clone()), "/api/status/200", Method::POST).await.unwrap();
        assert!(response.remote_addr().unwrap().is_ipv6());
        let body: Value = response.json().await.unwrap();
        assert_eq!(body["host"], format!("[::1]:{}", p.0.port().unwrap()));
        unavailable(); expire();
        assert!(use_primary(&literal).await.unwrap());
        for code in [401, 403, 429, 500, 502, 503, 504] {
            reset();
            let before = stats(&p.1).await;
            let r = request(p.clone(), &format!("/api/status/{code}"), Method::POST).await.unwrap();
            assert_eq!(r.status().as_u16(), code);
            assert_eq!(state().lock().unwrap().phase, Phase::Primary);
            assert_eq!(stats(&p.1).await, before, "business status must not replay POST");
        }
        reset();
        let r = request(p.clone(), "/api/redirect", Method::GET).await.unwrap();
        assert_eq!(r.status().as_u16(), 302);
        // IPv4-only resolution, nonexistent DNS, closed TCP and blackholed TLS.
        for endpoint in [p.1.as_str().to_owned(), "https://no-such-api.invalid".to_owned(),
            std::env::var("API_TEST_CLOSED").unwrap(),
            std::env::var("API_TEST_BLACKHOLE").unwrap()] {
            reset();
            let started = Instant::now();
            let r = request((Url::parse(&endpoint).unwrap(), p.1.clone()), "/api/status/200", Method::POST).await.unwrap();
            assert!(started.elapsed() < Duration::from_secs(5), "serial preparation must be bounded");
            assert!(r.remote_addr().unwrap().is_ipv4());
            let body: Value = r.json().await.unwrap();
            assert_eq!(body["authorization"], "Bearer fixture-only");
            assert_eq!(body["host"], format!("127.0.0.1:{}", p.1.port().unwrap()));
            assert_eq!(state().lock().unwrap().phase, Phase::Fallback);
        }
        // An untrusted / mismatched primary certificate is visible, never
        // concealed by sending the business operation to fallback.
        reset();
        let before = stats(&p.1).await;
        let error = request((Url::parse(&std::env::var("API_TEST_BAD_TLS").unwrap()).unwrap(), p.1.clone()), "/api/status/200", Method::POST).await.unwrap_err();
        assert!(error.contains("TLS validation/negotiation"), "{error}");
        assert_eq!(stats(&p.1).await, before);
        assert_eq!(state().lock().unwrap().phase, Phase::Primary);
        unavailable();
        // During cooldown the healthy primary is not even probed.
        let before = stats(&p.0).await;
        let r = request(p.clone(), "/api/status/503", Method::POST).await.unwrap();
        assert_eq!(r.status().as_u16(), 503);
        assert_eq!(stats(&p.0).await, before);
        // No-auth HEAD restores Primary even with 404 (the earlier literal probe returned 401).
        expire();
        let r = request(p.clone(), "/api/status/200", Method::POST).await.unwrap();
        assert!(r.remote_addr().unwrap().is_ipv6());
        let after = stats(&p.0).await;
        assert_eq!(after["probe_auth"], "");
        assert_eq!(after["probe_method"], "HEAD");
        assert_eq!(after["probe_status"], 404);
        assert_eq!(state().lock().unwrap().phase, Phase::Primary);
        // Accepted POST then lost response: never replay the uncertain operation.
        let before = stats(&p.1).await;
        assert!(request(p.clone(), "/api/drop", Method::POST).await.is_err());
        assert_eq!(stats(&p.1).await, before);
        reset();
        let before = stats(&p.1).await;
        assert!(request(p.clone(), "/api/slow", Method::POST).await.is_err());
        assert_eq!(stats(&p.1).await, before);
        // Headers alone do not prove a complete response. Report body loss to
        // shared state, but never repeat this accepted POST (review P2).
        for path in ["/api/body-drop", "/api/body-stall"] {
            reset();
            let before = stats(&p.1).await;
            let response = request(p.clone(), path, Method::POST).await.unwrap();
            assert_eq!(response.status().as_u16(), 200);
            assert!(read_text_for(response, &p.0).await.is_err());
            assert_eq!(stats(&p.1).await, before, "body failure must not replay");
            assert_eq!(state().lock().unwrap().phase, Phase::Fallback);
            let remaining = state().lock().unwrap().retry_at.unwrap().saturating_duration_since(Instant::now());
            assert!(remaining <= Duration::from_secs(15) && remaining > Duration::from_secs(13));
            let response = request(p.clone(), "/api/status/200", Method::POST).await.unwrap();
            assert!(response.remote_addr().unwrap().is_ipv4(), "only the next request switches");
            read_text_for(response, &p.0).await.unwrap();
        }
        // A recovery HEAD must propagate certificate failure too: it cannot
        // silently send the initiating API/recording operation to fallback.
        let bad = Url::parse(&std::env::var("API_TEST_BAD_TLS").unwrap()).unwrap();
        for recording in [false, true] {
            unavailable(); expire();
            let before = stats(&p.1).await;
            let value = bad.join("/api/record").unwrap().to_string();
            let error = if recording {
                recording_endpoint_for(&value, (bad.clone(), p.1.clone()), None).await.err().expect("probe certificate must fail")
            } else {
                request((bad.clone(), p.1.clone()), "/api/status/200", Method::POST).await.unwrap_err()
            };
            assert!(error.contains("TLS validation/negotiation"), "{error}");
            assert_eq!(stats(&p.1).await, before, "security error must stop the initiating operation");
            assert_eq!(state().lock().unwrap().phase, Phase::Fallback);
        }
        // A cancelled recovery lease cannot leave recovery stuck forever.
        { let mut s = state().lock().unwrap(); s.phase = Phase::RecoveryProbe; }
        expire();
        assert!(use_primary(&p.0).await.unwrap());
        assert_eq!(stats(&p.0).await["probe_status"], 405);
        // Concurrent recovery opportunities still deliver each business request once.
        unavailable(); expire();
        let before = stats(&p.0).await["requests"].as_u64().unwrap()
            + stats(&p.1).await["requests"].as_u64().unwrap();
        let (a, b) = tokio::join!(request(p.clone(), "/api/status/200", Method::POST), request(p.clone(), "/api/status/200", Method::POST));
        assert!(a.is_ok() && b.is_ok());
        let after = stats(&p.0).await["requests"].as_u64().unwrap()
            + stats(&p.1).await["requests"].as_u64().unwrap();
        assert_eq!(after - before, 2);
        // FRP/fallback outage is an error, with no loop or downgrade.
        unavailable();
        assert!(request((p.0.clone(), Url::parse(&std::env::var("API_TEST_CLOSED").unwrap()).unwrap()), "/api/status/200", Method::POST).await.is_err());
        // Exercise actual recording selection AND its production blocking client
        // through IPv4/IPv6 CONNECT proxies. A proxy peer is never origin-pinned.
        for proxy_key in [None, Some("API_TEST_PROXY4"), Some("API_TEST_PROXY6")] {
            reset();
            let proxy = proxy_key.map(|key| reqwest::Proxy::all(std::env::var(key).unwrap()).unwrap());
            let value = p.0.join("/api/record").unwrap().to_string();
            let before = stats(&p.1).await;
            let primary_before = stats(&p.0).await["requests"].as_u64().unwrap();
            let selected = recording_endpoint_for(&value, p.clone(), proxy).await.unwrap();
            assert_eq!(Url::parse(&selected.url).unwrap().origin(), p.0.origin());
            assert_eq!(selected.addr.is_none(), proxy_key.is_some());
            assert_eq!(selected.proxy.is_some(), proxy_key.is_some());
            assert_eq!(state().lock().unwrap().phase, Phase::Primary);
            let (remote, body) = tokio::task::spawn_blocking(move || {
                let response = selected.client().unwrap().post(&selected.url)
                    .header("Authorization", "Bearer fixture-recording")
                    .body("single-recording-chunk").send().unwrap();
                assert_eq!(response.status().as_u16(), 200);
                (response.remote_addr().unwrap(), response.json::<Value>().unwrap())
            }).await.unwrap();
            assert_eq!(remote.is_ipv4(), proxy_key == Some("API_TEST_PROXY4"));
            assert_eq!(body["authorization"], "Bearer fixture-recording");
            assert_eq!(body["body"], "single-recording-chunk");
            assert_eq!(body["host"], format!("localhost:{}", p.0.port().unwrap()));
            assert_eq!(stats(&p.1).await, before, "successful proxied TLS must not select fallback");
            assert_eq!(stats(&p.0).await["requests"].as_u64().unwrap(), primary_before + 1);
            assert_eq!(stats(&p.0).await["probe_auth"], "");
        }
        // This fixture enables native-tls like upstream. On Linux this executes
        // the updated OpenSSL dependency, rather than only compiling it while
        // all selector requests use rustls. Trust only the temporary test CA.
        let ca = std::fs::read(std::env::var("SSL_CERT_FILE").unwrap()).unwrap();
        let native = Client::builder().no_proxy().use_native_tls().https_only(true)
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(3))
            .add_root_certificate(reqwest::Certificate::from_pem(&ca).unwrap())
            .build().unwrap();
        let response = native.get(p.0.join("/api/status/200").unwrap()).send().await.unwrap();
        assert_eq!(response.status().as_u16(), 200);
        response.text().await.unwrap();
        let bad = Url::parse(&std::env::var("API_TEST_BAD_TLS").unwrap()).unwrap();
        assert!(native.get(bad.join("/api/status/200").unwrap()).send().await.is_err(),
            "native TLS must still reject the untrusted server certificate");
        let mut headers = HeaderMap::new(); headers.insert("Host", "bad.invalid".parse().unwrap());
        assert!(send_for(p.clone(), p.0.join("/api/login").unwrap().as_str(), Method::POST, headers, None).await.is_err());
        // Assert actual local-TLS selector events, not string matches on patch text.
        let mut records = serde_json::json!([]);
        for _ in 0..20 {
            records = engine.request(serde_json::json!({"op":"query","query":{"module":"api"}})).unwrap();
            if records.as_array().unwrap().iter().any(|v|v["action"]=="api_request" && v["status"]==200) { break; }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        assert!(records.as_array().unwrap().iter().any(|v|v["action"]=="api_request" && v["status"]==200));
        let text=records.to_string();
        for secret in ["fixture-only","fixture-body","Authorization","127.0.0.1","localhost"] { assert!(!text.contains(secret),"private request material reached diagnostics"); }
        let request_records:Vec<_>=records.as_array().unwrap().iter().filter(|v|v["action"]=="api_request").collect();
        assert!(request_records.iter().all(|v|v["session"].as_str().is_some_and(|v|v.len()==24)));
        let body_records:Vec<_>=records.as_array().unwrap().iter().filter(|v|v["action"]=="api_response_body").collect();
        assert!(!body_records.is_empty(),"body-read diagnostics must be captured");
        assert!(body_records.iter().all(|v|request_records.iter().any(|request|request["session"]==v["session"])),"body completion/failure must retain its request context");
        let identities:std::collections::HashSet<_>=request_records.iter().map(|v|v["session"].to_string()).collect();
        assert!(identities.len()>=2,"independent API calls must not share an accidental task-local identity");
        engine.request(serde_json::json!({"op":"stop"})).unwrap();

    }
}

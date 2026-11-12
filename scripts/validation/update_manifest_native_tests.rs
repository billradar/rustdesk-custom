use rustdesk_update_manifest::{verify, verify_proof, Expected, Manifest, linux_package_format};
use serde_json::{Value, json};
fn expected()->Expected<'static>{Expected{repository:"billradar/rustdesk-custom",repository_id:"1399548376",owner_id:"56966687",tag:"v1.5.3-custom.v3.1"}}
fn fixture(name:&str)->Vec<u8>{std::fs::read(std::path::Path::new(&std::env::var("UPDATE_FIXTURES").unwrap()).join(name)).unwrap()}
fn value()->Value{serde_json::from_slice(&fixture("schema-v2-unsigned.json")).unwrap()}
fn parse(v:&Value)->Result<Manifest,String>{Manifest::parse(&serde_json::to_vec(v).unwrap(),expected())}
#[test]
fn actual_cd_proof_verifies_and_tampering_fails(){
 let raw=fixture("cd-v1-manifest.json");let proof=fixture("cd-v1-attestation.json");
 let sha="c1d6942ee173979a8d73c393a7ceb12abda20186";
 verify_proof(&raw,&proof,expected(),sha,"43146078797").unwrap();
 let mut changed=raw.clone();changed.push(b' ');
 assert!(verify_proof(&changed,&proof,expected(),sha,"43146078797").is_err());
 assert!(verify_proof(&raw,&proof,expected(),sha,"43146078798").is_err());
 assert!(verify_proof(&raw,&proof,expected(),&"d".repeat(40),"43146078797").is_err());
 let wrong=Expected{repository_id:"1",..expected()};
 assert!(verify_proof(&raw,&proof,wrong,sha,"43146078797").is_err());
 let wrong=Expected{owner_id:"1",..expected()};
 assert!(verify_proof(&raw,&proof,wrong,sha,"43146078797").is_err());
 let wrong=Expected{repository:"other/repo",..expected()};
 assert!(verify_proof(&raw,&proof,wrong,sha,"43146078797").is_err());
 assert!(verify_proof(&raw,b"{}",expected(),sha,"43146078797").is_err());
 // Historical signed v1 verifies cryptographically but is never accepted as v2.
 assert!(verify(&raw,&proof,expected()).is_err());
 // A constructed v2 fixture is parser evidence, never fabricated signing evidence.
 assert!(verify(&fixture("schema-v2-unsigned.json"),&proof,expected()).is_err());
}
#[test]
fn typed_selection_covers_all_31_installers_and_rejects_missing_or_ambiguous(){
 let m=parse(&value()).unwrap();assert_eq!(m.assets.len(),31);
 for p in &m.assets{
  assert_eq!(m.selected(&p.os,&p.arch,&p.variant,p.flavor=="unattended-wayland",&p.package).unwrap(),p);
 }
 assert!(m.selected("macos","armv7","sos",false,"dmg").is_err());
 assert!(m.selected("android","aarch64","sos",false,"apk").is_err());
 let mut duplicated=m.clone();duplicated.assets.push(m.assets[0].clone());
 let p=&m.assets[0];assert!(duplicated.selected(&p.os,&p.arch,&p.variant,false,&p.package).is_err());
 // A signed typed selector is authoritative; filenames need not be predicted.
 let mut renamed=value();renamed["assets"][0]["name"]=json!("renamed-release.apk");
 assert_eq!(parse(&renamed).unwrap().selected("android","aarch64","standard",false,"apk").unwrap().name,"renamed-release.apk");
}
#[test]
fn malformed_schema_identity_options_and_inventory_fail_closed(){
 for (k,v) in [("schema",json!("rustdesk-release-manifest-v1")),("channel",json!("nightly")),("repository_id",json!("1")),("repository_owner_id",json!("1")),("upstream_sha",json!("bad")),("build_identity",json!("0".repeat(64))),("patchset_version",json!("v3.2")),("prepare_run",json!("0")),("wayland_included",json!(false)),("android_production_signed",json!(false))]{
  let mut m=value();m[k]=v;assert!(parse(&m).is_err(),"{k}");
 }
 for (k,v) in [("name",json!("../escape.apk")),("size",json!(0)),("sha256",json!("x".repeat(64))),("os",json!("unknown")),("flavor",json!("other")),("signing_status",json!("unreviewed"))]{
  let mut m=value();m["assets"][0][k]=v;assert!(parse(&m).is_err(),"{k}");
 }
 let mut duplicate=value();let p=duplicate["assets"][0].clone();duplicate["assets"].as_array_mut().unwrap().push(p);assert!(parse(&duplicate).is_err());
 let raw=String::from_utf8(fixture("schema-v2-unsigned.json")).unwrap().replacen("{","{\"schema\":\"duplicate\",",1);
 assert!(Manifest::parse(raw.as_bytes(),expected()).is_err());
 assert!(Manifest::parse(&vec![b' ';1024*1024+1],expected()).is_err());
}
#[test]
fn package_format_uses_actual_owner_and_exact_distro_tokens(){
 assert_eq!(linux_package_format(true,false,false,"").unwrap(),"deb");
 assert_eq!(linux_package_format(false,true,false,"ID=fedora\n").unwrap(),"rpm");
 assert_eq!(linux_package_format(false,true,false,"ID=opensuse-tumbleweed\n").unwrap(),"suse.rpm");
 assert_eq!(linux_package_format(false,true,false,"ID=custom\nID_LIKE=\"suse fedora\"\n").unwrap(),"suse.rpm");
 assert_eq!(linux_package_format(false,true,false,"ID=not-suse\nID_LIKE=notsuse\n").unwrap(),"rpm");
 for (d,r,w,id) in [(false,false,false,"ID=fedora"),(true,true,false,"ID=fedora"),(false,true,true,"ID=suse"),(false,true,false,""),(false,true,false,"ID=fedora\nID=suse")]{assert!(linux_package_format(d,r,w,id).is_err());}
}

// GitHub native Release service uses its own CA and mandatory signed TSA evidence.
// This test does not change the production updater's Actions/Rekor verification policy.
fn native_fixture_verify(raw:&[u8], digest:&str, identity:&str, github_root:bool)->Result<(),String>{
 use sigstore_verify::{trust_root::{TrustedRoot,SIGSTORE_GITHUB_TRUSTED_ROOT,SIGSTORE_PRODUCTION_TRUSTED_ROOT},types::{Artifact,Bundle,Sha256Hash},VerificationPolicy};
 let bundle=Bundle::from_json(std::str::from_utf8(raw).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
 if bundle.verification_material.timestamp_verification_data.rfc3161_timestamps.is_empty(){return Err("Native proof requires GitHub TSA evidence".into());}
 let root=TrustedRoot::from_json(if github_root{SIGSTORE_GITHUB_TRUSTED_ROOT}else{SIGSTORE_PRODUCTION_TRUSTED_ROOT}).map_err(|e|e.to_string())?;
 let policy=VerificationPolicy::default().require_identity(identity).skip_tlog().skip_sct();
 let hash=Sha256Hash::from_hex(digest).map_err(|e|e.to_string())?;
 sigstore_verify::verify(Artifact::from_digest(hash.as_bytes()),&bundle,&policy,&root).map_err(|e|e.to_string())?;
 Ok(())
}
#[test]
fn actual_native_release_proof_requires_github_chain_signature_digest_and_tsa(){
 let raw=fixture("native-release-reference.json");let digest="0915c496189e2130b4cbd754f3de0cefc5b35a74951115d0e0610ce8b89f2534";let signer="https://dotcom.releases.github.com";
 native_fixture_verify(&raw,digest,signer,true).unwrap();
 assert!(native_fixture_verify(&raw,&"0".repeat(64),signer,true).is_err());
 assert!(native_fixture_verify(&raw,digest,"https://other.releases.github.com",true).is_err());
 assert!(native_fixture_verify(&raw,digest,signer,false).is_err());
 let value:Value=serde_json::from_slice(&raw).unwrap();
 let mut missing=value.clone();missing["verificationMaterial"]["timestampVerificationData"]["rfc3161Timestamps"]=json!([]);
 assert!(native_fixture_verify(&serde_json::to_vec(&missing).unwrap(),digest,signer,true).is_err());
 for path in ["signature","timestamp"]{
  let mut changed=value.clone();
  let field=if path=="signature"{&mut changed["dsseEnvelope"]["signatures"][0]["sig"]}else{&mut changed["verificationMaterial"]["timestampVerificationData"]["rfc3161Timestamps"][0]["signedTimestamp"]};
  let original=field.as_str().unwrap();let replacement=if original.starts_with('A'){"B"}else{"A"};*field=json!(replacement.to_owned()+&original[1..]);
  assert!(native_fixture_verify(&serde_json::to_vec(&changed).unwrap(),digest,signer,true).is_err(),"{path}");
 }
}

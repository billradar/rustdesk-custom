use rustdesk_update_manifest::{verify, verify_release_proof, validate_release_statement, Expected, Manifest, linux_package_format};
use serde_json::{Value, json};
fn expected()->Expected<'static>{Expected{repository:"billradar/rustdesk-custom",repository_id:"1399548376",owner_id:"56966687",tag:"v1.5.3-custom.v3.1"}}
fn fixture(name:&str)->Vec<u8>{std::fs::read(std::path::Path::new(&std::env::var("UPDATE_FIXTURES").unwrap()).join(name)).unwrap()}
fn value()->Value{serde_json::from_slice(&fixture("schema-v2-unsigned.json")).unwrap()}
fn parse(v:&Value)->Result<Manifest,String>{Manifest::parse(&serde_json::to_vec(v).unwrap(),expected())}
#[test]
fn historical_build_proofs_and_unsigned_manifests_are_not_native_release_proofs(){
 let proof=fixture("cd-v1-attestation.json");
 for name in ["cd-v1-manifest.json", "schema-v2-unsigned.json"] {
  assert!(verify(&fixture(name),&proof,expected(),442501039,&"a".repeat(40)).is_err());
 }
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

fn native_expected()->Expected<'static>{Expected{repository:"VeryBaaad/ZNNext",repository_id:"1348255159",owner_id:"245651649",tag:"v2.16.0"}}
fn native_files()->std::collections::BTreeMap<String,String>{
 [("ZNNext-v2.16.0-371-52b358c-release.zip".into(),"0915c496189e2130b4cbd754f3de0cefc5b35a74951115d0e0610ce8b89f2534".into())].into()
}
const NATIVE_TAG_SHA:&str="7c57ae01206d1ae02164f85f343020f91a768991";
#[test]
fn actual_native_release_proof_uses_the_production_verifier(){
 let raw=fixture("native-release-reference.json");
 verify_release_proof(&raw,native_expected(),438125342,NATIVE_TAG_SHA,&native_files()).unwrap();
 for wrong in [Expected{repository:"other/repo",..native_expected()},Expected{repository_id:"1",..native_expected()},Expected{owner_id:"1",..native_expected()},Expected{tag:"v2.16.1",..native_expected()}]{
  assert!(verify_release_proof(&raw,wrong,438125342,NATIVE_TAG_SHA,&native_files()).is_err());
 }
 assert!(verify_release_proof(&raw,native_expected(),1,NATIVE_TAG_SHA,&native_files()).is_err());
 assert!(verify_release_proof(&raw,native_expected(),438125342,&"a".repeat(40),&native_files()).is_err());
 let mut files=native_files(); files.insert("extra.deb".into(),"a".repeat(64));
 assert!(verify_release_proof(&raw,native_expected(),438125342,NATIVE_TAG_SHA,&files).is_err());
 let mut files=native_files(); *files.values_mut().next().unwrap()="0".repeat(64);
 assert!(verify_release_proof(&raw,native_expected(),438125342,NATIVE_TAG_SHA,&files).is_err());
 let value:Value=serde_json::from_slice(&raw).unwrap();
 let mut missing=value.clone();missing["verificationMaterial"]["timestampVerificationData"]["rfc3161Timestamps"]=json!([]);
 assert!(verify_release_proof(&serde_json::to_vec(&missing).unwrap(),native_expected(),438125342,NATIVE_TAG_SHA,&native_files()).is_err());
 for field in ["signature","timestamp"]{
  let mut changed=value.clone();
  let slot=if field=="signature"{&mut changed["dsseEnvelope"]["signatures"][0]["sig"]}else{&mut changed["verificationMaterial"]["timestampVerificationData"]["rfc3161Timestamps"][0]["signedTimestamp"]};
  let original=slot.as_str().unwrap();let first=if original.starts_with('A'){"B"}else{"A"};*slot=json!(first.to_owned()+&original[1..]);
  assert!(verify_release_proof(&serde_json::to_vec(&changed).unwrap(),native_expected(),438125342,NATIVE_TAG_SHA,&native_files()).is_err());
 }
 // The reference is a real proof for another repository, never signing evidence for ours.
 assert!(verify(&fixture("schema-v2-unsigned.json"),&raw,expected(),438125342,NATIVE_TAG_SHA).is_err());
}
#[test]
fn native_statement_rejects_duplicate_subjects_and_identity_changes(){
 let raw=fixture("native-release-reference.json");
 let bundle=sigstore_verify::types::Bundle::from_json(std::str::from_utf8(&raw).unwrap()).unwrap();
 let envelope=match bundle.content {sigstore_verify::types::SignatureContent::DsseEnvelope(v)=>v,_=>panic!("not DSSE")};
 let statement:Value=serde_json::from_slice(envelope.payload.as_bytes()).unwrap();
 validate_release_statement(&statement,native_expected(),438125342,NATIVE_TAG_SHA,&native_files()).unwrap();
 for key in ["databaseId","ownerId","repositoryId","packageId","repository","tag","purl"] {
  let mut changed=statement.clone();changed["predicate"][key]=json!("wrong");
  assert!(validate_release_statement(&changed,native_expected(),438125342,NATIVE_TAG_SHA,&native_files()).is_err());
 }
 for index in [0,1] {
  let mut changed=statement.clone();let duplicate=changed["subject"][index].clone();changed["subject"].as_array_mut().unwrap().push(duplicate);
  assert!(validate_release_statement(&changed,native_expected(),438125342,NATIVE_TAG_SHA,&native_files()).is_err());
 }
}

#[test]
fn native_api_discovery_rejects_ambiguous_missing_and_foreign_proofs(){
 use rustdesk_update_manifest::native_bundle;
 let bundle:Value=serde_json::from_slice(&fixture("native-release-reference.json")).unwrap();
 let row=json!({"initiator":"github","repository_id":1348255159u64,"bundle":bundle});
 let response=json!({"attestations":[row.clone()]});
 let raw=native_bundle(&response,"1348255159").unwrap();
 verify_release_proof(&raw,native_expected(),438125342,NATIVE_TAG_SHA,&native_files()).unwrap();
 for wrong in [json!({}),json!({"attestations":[]}),json!({"attestations":[row.clone(),row.clone()]}),
  json!({"attestations":[{"initiator":"actions","repository_id":1348255159u64,"bundle":bundle}]}),
  json!({"attestations":[{"initiator":"github","repository_id":1348255159u64}]}),
 ]{assert!(native_bundle(&wrong,"1348255159").is_err());}
 assert!(native_bundle(&response,"1").is_err());
}

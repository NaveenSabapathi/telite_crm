# Android packaging and Play Store plan

Phase 1 design and future execution guide, reviewed 14 November 2026. No Android project, plugin integration, signing key or AAB is generated in this phase. Policy compliance depends on the final app/SDK behavior and Google review; approval is not guaranteed. Recheck linked official requirements, target SDK deadlines and developer-account testing rules at release.

## Packaging choice

Use Capacitor with bundled `frontend/dist` web assets, communicating with HTTPS API. This supports native camera/scanner, location, FCM and Android device authentication while sharing responsive React UI. A TWA is an alternative for a simpler PWA, but does not supply the native capabilities assumed in this design. No release remote server URL or arbitrary WebView navigation. Open external URLs in system browser; allowlist deep links.

Planned `frontend/capacitor.config.json` (example, not committed executable release configuration):

```json
{
  "appId": "com.telitesystems.crm",
  "appName": "Telite CRM",
  "webDir": "dist",
  "server": { "androidScheme": "https", "cleartext": false }
}
```

App ID, final domain and developer identity must be finalized before first release. This proposed ID is not a claim of ownership/availability. API base URL is a public frontend build variable; all provider/admin secrets remain on server. Allow only actual native origin in CORS (normally `https://localhost` for this Android configuration), never `*` with credentials. Prefer bearer flow on native, HttpOnly refresh cookie on same-origin web.

## Native capability adapters

| Capability | Implementation plan | Fallback / release evidence |
|---|---|---|
| Foreground GPS | `@capacitor/geolocation`; fresh high-accuracy request after disclosure | Browser geolocation; denied/approximate → retry/review |
| Background travel | Separate reviewed native background plugin or custom foreground-service implementation | OFF by default; compatibility/license/battery/privacy review and physical-device proof required before enabling |
| Camera / selfie / job photo | `@capacitor/camera`, minimize file permissions | Browser file capture/manual upload; validate and scan server-side |
| Serial/barcode | Official Capacitor barcode scanner adapter after Android compatibility check | Manual serial entry always available; confirm detected serial |
| FCM | `@capacitor/push-notifications` with Firebase Android setup | Durable in-app inbox when permission denied; no guaranteed delivery time |
| Biometric/PIN | Android BiometricPrompt with device-credential fallback through reviewed plugin/custom bridge | Server login when unsupported; Keystore encryption and lock on background |
| Connectivity | `@capacitor/network` + actual API results | Online indicator is advisory; idempotent replay handles dropped responses |

The core Geolocation plugin does **not** itself implement background geolocation. Background travel remains a required optional product mode with its own release gate, not a capability inferred from foreground watchPosition. Do not pick an unverified plugin version in the design. Pin all selected packages to one compatible Capacitor major and validate transitive Android SDKs/licenses in Phase 5.

## Location privacy behavior

Foreground disclosure example: “Telite CRM uses your location when you punch attendance or check in/out of a customer job. Your company administrator can view these work locations and their timestamps. You can decline and request a reviewed attendance or service exception.” Show before Android permission prompt; record policy version and affirmative choice. Do not bundle consent with unrelated terms.

Separate background disclosure example: “When you start Work Travel, Telite CRM collects location to record your work route and show your latest work location to your company administrator, including while the app is closed or not in use. Tracking ends when you stop Work Travel or your shift ends.” Display a persistent tracking notification and Stop action; never auto-resume off-shift or collect before consent. Request background permissions separately only when necessary for the selected implementation and justified core feature. Force stop, reboot, revoked permission, battery restrictions and denied permission must be tested. Continuous tracking without explicit work-session boundaries is not permitted by this product design.

Request permissions in context; avoid asking for camera/location/notifications all at launch. No contacts/SMS/call-log/storage-wide permissions. Use customer OTP through server-side provider, not reading SMS on employee phones. Selfie/signature uploads are optional/required according to specific workflow, never covert captures.

## Manifest plan

Baseline permissions (merged manifest must be reviewed, including plugins):

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
<uses-permission android:name="android.permission.CAMERA" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
<uses-permission android:name="android.permission.USE_BIOMETRIC" />
<uses-feature android:name="android.hardware.camera" android:required="false" />
<uses-feature android:name="android.hardware.location.gps" android:required="false" />
```

Runtime requests still required where applicable; manifest permission alone does not grant access. Camera/scanner implementation determines whether CAMERA is needed; avoid unneeded declarations. Background-enabled flavor may additionally need `ACCESS_BACKGROUND_LOCATION`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION` and service `foregroundServiceType="location"` based on actual native implementation/target Android rules. These are not included blindly in the foreground-only flavor. Permission-gated build must match Play declarations and store description.

App links: configured Activity intent filter uses `android:autoVerify="true"`, actual HTTPS host and allowed paths. Serve `https://<owned-domain>/.well-known/assetlinks.json`, content type application/json, publicly reachable over valid HTTPS. Example template:

```json
[{
  "relation": ["delegate_permission/common.handle_all_urls"],
  "target": {
    "namespace": "android_app",
    "package_name": "com.telitesystems.crm",
    "sha256_cert_fingerprints": ["REPLACE_WITH_PLAY_APP_SIGNING_CERT_SHA256"]
  }
}]
```

Use Play **app signing certificate**, not only local upload certificate; include other authorized fingerprints only where needed. Asset Links establishes verified app/domain links (and is central to TWA verification); it is not a prerequisite for merely rendering bundled Capacitor UI. Deep links must not accept tokens from arbitrary hosts or grant access without normal authentication.

## Future build and signing workflow

After Phase 3 frontend exists, create Android project in Phase 5 with compatible pinned tooling. Commands below are a workflow, not runnable deliverables in this Phase 1-only repo:

```bash
cd frontend
npm ci
npm run build
npx cap add android
npx cap sync android
npx cap open android
```

`cap add` runs once; subsequent builds use `sync`. Use tested Node/JDK/Android SDK versions required by the pinned Capacitor release, Gradle wrapper committed to repo, reproducible lockfile and SDK version values. Place project-specific `google-services.json` via controlled build setup and configure package binding; Firebase Admin service-account key never belongs in app/assets or Git. Restrict any public map API keys by application/domain and API.

Create upload key outside repository (interactive password prompt):

```bash
keytool -genkeypair -v -keystore telite-crm-upload.jks -alias upload -keyalg RSA -keysize 2048 -validity 10000
```

Back up upload key securely; use Play App Signing, separate upload and app signing identities. Gradle release signing reads CI secrets/secure keystore, not committed passwords. Future release build:

```bash
cd frontend/android
./gradlew clean bundleRelease
```

Expected AAB path: `app/build/outputs/bundle/release/app-release.aab` after signing configuration. Increment versionCode, test release variant, verify signing and merged permissions, scan dependencies and produce SBOM. Upload first to internal testing; run physical-device validation and Play pre-launch report, then eligible closed/production track. Account-specific testing and review requirements must be checked in Play Console, not assumed from this document. No unattended public publication as part of Phase 1.

## Data Safety worksheet — provisional answers, not a submitted declaration

| Data category | Planned collection/use | What to verify for actual submission |
|---|---|---|
| Personal info | Name,email,phone,employee/company IDs for account/work assignment | Collection required for accounts; data sharing/provider terms and deletion behavior |
| Location | Precise work check-ins; optional active travel routes | Optional vs required per function, background behavior, retention and disclosures |
| Photos/videos | Job photos, optional selfie, signatures stored as images | Required for relevant completion; no face recognition; media access and retention |
| Files/documents | Quotes, service documents, report exports | User-provided documents and company/customer access scope |
| App activity | Attendance, ticket/lead actions and audit events | Classification of each event, purposes, retained history |
| Device identifiers | Resettable installation ID, push token | Actual SDK identifier collection and processor behavior |
| Financial info | Service payment amount/mode/reference, not card credentials | Exact fields and Data Safety category mapping; no claim of payment verification |
| Diagnostics | Minimal operational errors, optional crash SDK only after review | Whether IP/device diagnostics are collected, shared or retained by SDKs |
| Biometric templates | No collection by app/server | Android OS-only local authentication confirmed |

Answer encryption-in-transit only after all API/object/provider traffic is verified TLS. Data sharing answers depend on processor contracts, SDK behavior and Google's definitions; “not sold” does not automatically mean “not shared.” No advertising purpose planned. Required/optional answers must reflect usable alternatives in the released app. Submit verified facts from SDK/network inventory, not this draft wholesale.

Privacy page must name the actual developer/app, describe collection/use/processors/security/retention/deletion and provide support contact. Public deletion page references exact app/developer and allows identity-verified request without app installation. In-app Settings → Privacy → Delete account initiates same flow. Company-managed accounts still receive a deletion path by design. Revoke access first; coordinate job reassignment and last-admin ownership transfer; erase credentials and unneeded personal data. Disclose legitimate retained records and retention duration; mere deactivation is insufficient. Implement restoration suppression so erased data is not silently resurrected from backups.

## Release blockers

Final domain/app ID/developer name and support/privacy URLs; compatible native dependency audit; signed physical-device release test; provider credentials (FCM, SMTP, optional SMS/geocoder); functional deletion path; actual data inventory and accurate Play form; permissions and background-location review where enabled; backup/restore evidence; no secrets or development server in release binary. Foreground-only release may ship before optional background mode only with that capability clearly disabled and store claims adjusted; it is not completion of the background requirement.

Official sources and recheck links are in [SOURCES.md](docs/SOURCES.md).

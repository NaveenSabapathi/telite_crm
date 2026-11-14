# Primary references

Reviewed 14 November 2026. Design decisions are ours; policies and API behavior must be checked again at implementation/release. No guarantee of store approval is implied.

- PostgreSQL row security: https://www.postgresql.org/docs/current/ddl-rowsecurity.html — policies, ownership and BYPASSRLS behavior; basis for runtime-role separation.
- PostgreSQL CREATE POLICY: https://www.postgresql.org/docs/current/sql-createpolicy.html — USING and WITH CHECK behavior.
- Capacitor Geolocation: https://capacitorjs.com/docs/apis/geolocation — foreground API, Android fine/coarse permissions, no direct background support.
- Capacitor Android release: https://capacitorjs.com/docs/android/deploying-to-google-play — native Android packaging/release path.
- Android App Links association: https://developer.android.com/training/app-links/configure-assetlinks — domain assetlinks file and signing identity.
- Firebase Android messaging: https://firebase.google.com/docs/cloud-messaging/android/get-started — Android Firebase client setup; recheck permission/version setup at implementation.
- Play background location: https://support.google.com/googleplay/android-developer/answer/9799150 — core-purpose justification, disclosure and review requirements.
- Play user data: https://support.google.com/googleplay/android-developer/answer/10144311 — privacy and account-deletion expectations.
- Play account deletion: https://support.google.com/googleplay/android-developer/answer/13327111 — in-app and external deletion pathway.

No current Play target SDK numeric deadline is asserted here. Release owner must consult the live Play Console requirements and current Capacitor/Android tooling documentation before building the final AAB.

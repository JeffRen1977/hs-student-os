// auth.js — where the browser gets its ID token. Plain JS (window.HSAuth; Node-testable).
//
// Modes:
// - "firebase": `window.HS_FIREBASE_CONFIG` is set. Firebase Auth (optionally the Auth
//   emulator via `window.HS_AUTH_EMULATOR_URL`) signs the student in; the backend
//   verifies the ID token. This is the only mode for deployed environments.
// - "local_emulator": no Firebase config AND both page and API are on localhost. Mints
//   Auth-emulator-format (unsigned) tokens for the *synthetic* fixture students. The
//   backend accepts these only when it runs with FIREBASE_AUTH_EMULATOR_HOST set, which
//   staging/production refuse at startup, so this cannot sign anyone into a real deploy.
// - "none": anything else. The app stays on the sign-in screen.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HSAuth = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const SYNTHETIC_STUDENTS = Object.freeze([
    { uid: "stu_alex", label: "Alex（合成学生，11 年级）" },
    { uid: "stu_beth", label: "Beth（合成学生，10 年级）" },
  ]);
  const DEV_UID_KEY = "hsos.localEmulatorUid";
  const FIREBASE_SDK = "https://www.gstatic.com/firebasejs/10.12.2/";

  function isLocalHost(hostname) {
    return hostname === "localhost" || hostname === "127.0.0.1";
  }

  function b64url(text) {
    const base64 = typeof btoa === "function" ? btoa(text) : Buffer.from(text, "binary").toString("base64");
    return base64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  // Same shape as tokens issued by the Firebase Auth emulator (alg "none", no signature).
  function emulatorToken(uid, projectId, nowMs) {
    const now = Math.floor((nowMs == null ? Date.now() : nowMs) / 1000);
    const claims = {
      iss: "https://securetoken.google.com/" + projectId,
      aud: projectId,
      auth_time: now,
      user_id: uid,
      sub: uid,
      iat: now,
      exp: now + 3600,
      firebase: { identities: {}, sign_in_provider: "password" },
    };
    return b64url(JSON.stringify({ alg: "none", typ: "JWT" })) + "." + b64url(JSON.stringify(claims)) + ".";
  }

  function chooseMode(options) {
    const o = options || {};
    if (o.firebaseConfig) return "firebase";
    let apiLocal = false;
    try { apiLocal = isLocalHost(new URL(o.apiBaseUrl).hostname); } catch (_e) { apiLocal = false; }
    if (isLocalHost(o.hostname) && apiLocal) return "local_emulator";
    return "none";
  }

  function createAuth(options) {
    const o = options || {};
    const mode = chooseMode(o);
    const storage = o.storage || null;
    const projectId = o.projectId || "demo-hs-student-os";
    let firebase = null; // { auth, mod }

    async function loadFirebase() {
      if (firebase) return firebase;
      const appMod = await import(FIREBASE_SDK + "firebase-app.js");
      const mod = await import(FIREBASE_SDK + "firebase-auth.js");
      const app = appMod.initializeApp(o.firebaseConfig);
      const auth = mod.getAuth(app);
      if (o.emulatorUrl) mod.connectAuthEmulator(auth, o.emulatorUrl, { disableWarnings: true });
      await auth.authStateReady();
      firebase = { auth: auth, mod: mod };
      return firebase;
    }

    return {
      mode: mode,
      students: mode === "local_emulator" ? SYNTHETIC_STUDENTS : [],
      currentUid: function () {
        if (mode === "local_emulator") return storage ? storage.getItem(DEV_UID_KEY) : null;
        return firebase && firebase.auth.currentUser ? firebase.auth.currentUser.uid : null;
      },
      getIdToken: async function () {
        if (mode === "local_emulator") {
          const uid = storage ? storage.getItem(DEV_UID_KEY) : null;
          return uid ? emulatorToken(uid, projectId) : null;
        }
        if (mode === "firebase") {
          const fb = await loadFirebase();
          return fb.auth.currentUser ? fb.auth.currentUser.getIdToken() : null;
        }
        return null;
      },
      signInLocal: function (uid) {
        if (mode !== "local_emulator") throw new Error("local emulator sign-in is not available here");
        if (!SYNTHETIC_STUDENTS.some(function (s) { return s.uid === uid; })) throw new Error("unknown synthetic student");
        storage.setItem(DEV_UID_KEY, uid);
      },
      signInWithPassword: async function (email, password) {
        if (mode !== "firebase") throw new Error("Firebase sign-in is not configured");
        const fb = await loadFirebase();
        await fb.mod.signInWithEmailAndPassword(fb.auth, email, password);
      },
      signOut: async function () {
        if (mode === "local_emulator" && storage) storage.removeItem(DEV_UID_KEY);
        if (mode === "firebase") {
          const fb = await loadFirebase();
          await fb.mod.signOut(fb.auth);
        }
      },
    };
  }

  return { createAuth: createAuth, chooseMode: chooseMode, emulatorToken: emulatorToken, SYNTHETIC_STUDENTS: SYNTHETIC_STUDENTS };
});

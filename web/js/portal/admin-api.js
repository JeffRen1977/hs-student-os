// Platform-wide publication; never addresses a student record.
(function (root, factory) {
  const portal = typeof module === "object" && module.exports ? require("./portal-api.js") : root.HSPortalApi;
  const api = factory(portal);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HSAdminApi = api;
})(typeof self !== "undefined" ? self : this, function (portal) {
  "use strict";
  function createAdminApi(options) {
    const request = portal.createRequester(options), enc = encodeURIComponent;
    return {
      queue: () => request("GET", "/api/admin/packages"),
      publish: (c, v) => request("POST", "/api/admin/packages/" + enc(c) + "/versions/" + enc(v) + "/activate", {}, "publish:" + c + "@" + v),
      retire: (c, notes) => request("POST", "/api/admin/courses/" + enc(c) + "/retire", { notes }, "retire:" + c + ":" + notes),
    };
  }
  function actionsFor(status) {
    return status === "approved" ? ["publish"] : status === "active" ? ["retire"] : [];
  }
  function adminErrorText(err) {
    const e = err || {};
    if (e.code === "FORBIDDEN") return "This account is not a platform admin.";
    if (e.code === "INVALID_STATE_TRANSITION") return "This version cannot be published or retired in its current state. Refresh the list.";
    return e.message || "Something went wrong.";
  }
  return { createAdminApi, actionsFor, adminErrorText };
});

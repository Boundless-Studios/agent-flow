(function () {
  const REFRESH_INTERVAL_MS = 10000;
  let pendingSnapshotInitialized = false;
  let knownPendingRequestIds = new Set();

  function desktopNotificationsSupported() {
    return typeof window.Notification !== "undefined";
  }

  function syncNotificationControls() {
    const enableButton = document.querySelector("[data-enable-notifications]");
    const state = document.querySelector("[data-notification-state]");
    if (!(enableButton instanceof HTMLButtonElement) || !(state instanceof HTMLElement)) {
      return;
    }

    if (!desktopNotificationsSupported()) {
      enableButton.hidden = true;
      state.classList.add("error");
      state.textContent = "Web notifications unavailable. Native desktop alerts will be used when available.";
      return;
    }

    state.classList.remove("error");
    if (Notification.permission === "granted") {
      enableButton.hidden = true;
      state.textContent = "Desktop notifications are enabled.";
      return;
    }

    if (Notification.permission === "denied") {
      enableButton.hidden = true;
      state.classList.add("error");
      state.textContent = "Browser notifications are blocked. Native desktop alerts will be used when available.";
      return;
    }

    enableButton.hidden = false;
    state.textContent = "Enable notifications for newly pending requests.";
  }

  async function requestNotificationPermission() {
    if (!desktopNotificationsSupported()) {
      return;
    }

    try {
      await Notification.requestPermission();
    } catch (_err) {
      // Keep UI state unchanged if permission flow fails.
    }
    syncNotificationControls();
  }

  function collectPendingRequests() {
    const requests = new Map();
    const items = document.querySelectorAll(".request-item[data-request-id]");
    for (const item of items) {
      const requestId = item.getAttribute("data-request-id");
      if (!requestId) {
        continue;
      }

      const title = item.querySelector(".title")?.textContent?.trim() || "Input Request";
      const priority = item.querySelector(".priority")?.textContent?.trim() || "NORMAL";
      const sessionId = item.querySelector("code")?.textContent?.trim() || "";
      const question = item.querySelector(".question")?.textContent?.trim() || "";
      requests.set(requestId, { requestId, title, priority, sessionId, question });
    }
    return requests;
  }

  function formatNotificationBody(requestInfo) {
    const lines = [];
    lines.push(`Priority: ${requestInfo.priority}`);
    if (requestInfo.sessionId) {
      lines.push(`Session: ${requestInfo.sessionId}`);
    }
    if (requestInfo.question) {
      const normalized = requestInfo.question.replace(/\s+/g, " ").trim();
      lines.push(normalized.length > 180 ? `${normalized.slice(0, 177)}...` : normalized);
    }
    return lines.join("\n");
  }

  function notifyForNewPendingRequests(currentPending) {
    if (!pendingSnapshotInitialized) {
      knownPendingRequestIds = new Set(currentPending.keys());
      pendingSnapshotInitialized = true;
      return;
    }

    if (!desktopNotificationsSupported() || Notification.permission !== "granted") {
      knownPendingRequestIds = new Set(currentPending.keys());
      return;
    }

    for (const [requestId, requestInfo] of currentPending.entries()) {
      if (knownPendingRequestIds.has(requestId)) {
        continue;
      }
      try {
        new Notification(`AgentFlow: ${requestInfo.title}`, {
          body: formatNotificationBody(requestInfo),
          tag: `agentflow-request-${requestId}`,
        });
      } catch (_err) {
        // Ignore notification API failures and keep the dashboard responsive.
      }
    }

    knownPendingRequestIds = new Set(currentPending.keys());
  }

  function postRefreshSync() {
    syncNotificationControls();
    notifyForNewPendingRequests(collectPendingRequests());
  }

  async function refreshSections() {
    const sections = document.querySelectorAll("[data-refresh-url]");
    if (!sections.length) {
      return;
    }

    await Promise.all(
      Array.from(sections).map(async (section) => {
        const refreshUrl = section.getAttribute("data-refresh-url");
        if (!refreshUrl) {
          return;
        }

        try {
          const response = await fetch(refreshUrl, { cache: "no-store" });
          if (!response.ok) {
            return;
          }
          section.innerHTML = await response.text();
        } catch (_err) {
          // Ignore transient refresh errors; next event/poll will retry.
        }
      })
    );

    postRefreshSync();
  }

  function attachEventStream() {
    if (typeof window.EventSource === "undefined") {
      return false;
    }

    const eventSource = new EventSource("/api/events");
    eventSource.onmessage = function () {
      void refreshSections();
    };
    eventSource.onerror = function () {
      // Keep stream open; browser will reconnect automatically.
    };
    return true;
  }

  async function submitInlineResponse(form) {
    const requestId = form.dataset.requestId;
    if (!requestId) {
      return;
    }

    const responseInput = form.querySelector("textarea[name='response_text']");
    const responderInput = form.querySelector("input[name='responder']");
    const statusEl = form.querySelector(".inline-response-status");
    const submitButton = form.querySelector("button[type='submit']");
    if (!(responseInput instanceof HTMLTextAreaElement)) {
      return;
    }

    const responseText = responseInput.value.trim();
    if (!responseText) {
      responseInput.focus();
      return;
    }

    const responder = responderInput instanceof HTMLInputElement ? responderInput.value || "human" : "human";
    if (statusEl instanceof HTMLElement) {
      statusEl.classList.remove("error");
      statusEl.textContent = "Sending response...";
    }
    if (submitButton instanceof HTMLButtonElement) {
      submitButton.disabled = true;
    }

    try {
      const response = await fetch(`/api/requests/${encodeURIComponent(requestId)}/respond`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        cache: "no-store",
        body: JSON.stringify({
          response_text: responseText,
          responder: responder,
        }),
      });

      if (!response.ok) {
        throw new Error(`Failed with status ${response.status}`);
      }

      if (statusEl instanceof HTMLElement) {
        statusEl.textContent = "Sent. Waiting for agent ACK.";
      }
      responseInput.value = "";
      const details = form.closest("details");
      if (details instanceof HTMLDetailsElement) {
        details.open = false;
      }
      await refreshSections();
    } catch (_err) {
      if (statusEl instanceof HTMLElement) {
        statusEl.classList.add("error");
        statusEl.textContent = "Failed to send. Please retry.";
      }
    } finally {
      if (submitButton instanceof HTMLButtonElement) {
        submitButton.disabled = false;
      }
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.addEventListener("click", function (event) {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }

      const button = target.closest("[data-enable-notifications]");
      if (!(button instanceof HTMLButtonElement)) {
        return;
      }

      event.preventDefault();
      void requestNotificationPermission();
    });

    document.addEventListener("submit", function (event) {
      const target = event.target;
      if (!(target instanceof HTMLFormElement) || !target.classList.contains("inline-response-form")) {
        return;
      }
      event.preventDefault();
      void submitInlineResponse(target);
    });

    postRefreshSync();

    const sseAttached = attachEventStream();
    if (!sseAttached) {
      setInterval(function () {
        void refreshSections();
      }, REFRESH_INTERVAL_MS);
    }
  });
})();

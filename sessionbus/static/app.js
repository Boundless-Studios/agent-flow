(function () {
  const REFRESH_INTERVAL_MS = 10000;

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
    document.addEventListener("submit", function (event) {
      const target = event.target;
      if (!(target instanceof HTMLFormElement) || !target.classList.contains("inline-response-form")) {
        return;
      }
      event.preventDefault();
      void submitInlineResponse(target);
    });

    const sseAttached = attachEventStream();
    if (!sseAttached) {
      setInterval(function () {
        void refreshSections();
      }, REFRESH_INTERVAL_MS);
    }
  });
})();

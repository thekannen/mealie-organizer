(() => {
  const basePath = window.__MO_BASE_PATH__ || "";
  const output = document.getElementById("output");
  const form = document.getElementById("login-form");
  const username = document.getElementById("username");
  const password = document.getElementById("password");

  async function write(text) {
    output.textContent = text;
  }

  async function request(path, body) {
    const response = await fetch(`${basePath}/api/v1${path}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify(body),
    });
    const text = await response.text();
    if (!response.ok) {
      throw new Error(text || `Request failed (${response.status})`);
    }
    return text;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await write("Authenticating...");
    try {
      await request("/auth/login", {
        username: String(username.value || "").trim(),
        password: String(password.value || ""),
      });
      await write(`Authenticated. Open ${basePath} for the full React Web UI.`);
    } catch (error) {
      await write(String(error));
    }
  });
})();
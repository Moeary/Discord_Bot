const healthBox = document.getElementById("healthBox");
const taxBox = document.getElementById("taxBox");
const commandBox = document.getElementById("commandBox");
const globalForm = document.getElementById("globalForm");
const guildForm = document.getElementById("guildForm");
const guildIdInput = document.getElementById("guildIdInput");
const aiOutput = document.getElementById("aiOutput");
const aiPrompt = document.getElementById("aiPrompt");

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || JSON.stringify(data));
  }
  return data;
}

function renderForm(form, settings, path) {
  form.innerHTML = "";
  Object.entries(settings).forEach(([key, value]) => {
    const wrapper = document.createElement("label");
    wrapper.innerHTML = `
      <span>${key}</span>
      <input name="${key}" value="${value ?? ""}" />
    `;
    form.appendChild(wrapper);
  });

  const button = document.createElement("button");
  button.className = "button";
  button.type = "submit";
  button.textContent = "保存";
  form.appendChild(button);

  form.onsubmit = async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const updates = {};
    for (const [key, value] of formData.entries()) {
      updates[key] = value;
    }
    try {
      const result = await requestJson(path, {
        method: "PATCH",
        body: JSON.stringify({ updates }),
      });
      renderForm(form, result, path);
      alert("保存成功");
    } catch (error) {
      alert(error.message);
    }
  };
}

function renderCommands(catalog) {
  const rows = catalog.commands
    .map(
      (item) => `
        <tr>
          <td>${item.group}</td>
          <td>${item.name}</td>
          <td>${item.description}</td>
        </tr>
      `
    )
    .join("");

  commandBox.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>分组</th>
          <th>命令</th>
          <th>说明</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

async function loadDashboard() {
  const guildId = guildIdInput.value.trim();
  const query = guildId ? `?guild_id=${guildId}` : "";
  const data = await requestJson(`/api/dashboard${query}`);
  healthBox.textContent = JSON.stringify(data.health, null, 2);
  taxBox.textContent = JSON.stringify(data.pending_tax_cases, null, 2);
  renderCommands(data.catalog);
  renderForm(globalForm, data.global_settings, "/api/settings/global");

  if (guildId) {
    const guildSettings = await requestJson(`/api/settings/guild/${guildId}`);
    renderForm(guildForm, guildSettings, `/api/settings/guild/${guildId}`);
  } else {
    guildForm.innerHTML = "<p>先输入 Guild ID 再加载服务器配置。</p>";
  }
}

document.getElementById("refreshButton").addEventListener("click", loadDashboard);
guildIdInput.addEventListener("change", loadDashboard);

document.getElementById("aiChatButton").addEventListener("click", async () => {
  try {
    const data = await requestJson("/api/ai/chat", {
      method: "POST",
      body: JSON.stringify({ prompt: aiPrompt.value }),
    });
    aiOutput.textContent = data.reply;
  } catch (error) {
    aiOutput.textContent = error.message;
  }
});

document.getElementById("aiSummaryButton").addEventListener("click", async () => {
  try {
    const data = await requestJson("/api/ai/summary", {
      method: "POST",
      body: JSON.stringify({ text: aiPrompt.value }),
    });
    aiOutput.textContent = data.summary;
  } catch (error) {
    aiOutput.textContent = error.message;
  }
});

loadDashboard().catch((error) => {
  healthBox.textContent = error.message;
});

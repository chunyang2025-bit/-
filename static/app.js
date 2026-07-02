const form = document.querySelector("#generateForm");
const notice = document.querySelector("#notice");
const apiStatus = document.querySelector("#apiStatus");
const resultTitle = document.querySelector("#resultTitle");
const excelLink = document.querySelector("#excelLink");
const videoPreview = document.querySelector("#videoPreview");

function yuan(value) {
  return `¥${Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`;
}

function setNotice(text, type = "info") {
  notice.textContent = text;
  notice.classList.toggle("error", type === "error");
}

function formPayload() {
  const data = new FormData(form);
  return {
    space_type: data.get("space_type"),
    house_property: data.get("house_property"),
    decor_style: data.get("decor_style"),
    area_sqm: Number(data.get("area_sqm")),
    budget_min: Number(data.get("budget_min")),
    budget_max: Number(data.get("budget_max")),
    video_focus: data.get("video_focus"),
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

function render(data) {
  resultTitle.textContent = data.design_plan.title;
  document.querySelector("#concept").textContent = `${data.design_plan.concept_summary} ${data.design_plan.style_description}`;
  document.querySelector("#lowBudget").textContent = yuan(data.budget.low_plan.total_price);
  document.querySelector("#highBudget").textContent = yuan(data.budget.high_plan.total_price);
  document.querySelector("#budgetDiff").textContent = data.budget.difference_summary;

  videoPreview.src = data.video.video_url;
  excelLink.href = data.excel.excel_url;
  excelLink.classList.remove("disabled");

  document.querySelector("#items").innerHTML = data.design_plan.items
    .map(
      (item) => `
        <div class="item-card">
          <strong>${item.name}</strong>
          <p>${item.material}｜${item.size}｜${item.scene}</p>
          <p>${item.taobao_keyword}</p>
        </div>
      `,
    )
    .join("");

  document.querySelector("#products").innerHTML = data.products.matches
    .map((match) => {
      const product = match.products[0];
      return `
        <div class="product-row">
          <div>
            <strong>${match.design_item.name}</strong>
            <p>${product ? product.title : "未匹配到商品"}</p>
          </div>
          <div class="price">${product ? yuan(product.coupon_price || product.price) : "-"}</div>
          <p>${product ? `${product.shop_name}<br>${product.sales} 销量` : "-"}</p>
          <p>${product ? `<a href="${product.item_url}" target="_blank" rel="noreferrer">淘宝直达</a><br>${product.source}` : "-"}</p>
        </div>
      `;
    })
    .join("");

  document.querySelector("#copies").innerHTML = data.publish_copies
    .map(
      (copy) => `
        <div class="copy-card">
          <strong>${copy.platform}｜${copy.title}</strong>
          <p>${copy.body}</p>
          <p>${copy.hashtags.map((tag) => `#${tag}`).join(" ")}</p>
        </div>
      `,
    )
    .join("");

  const warning = data.warnings.length ? ` ${data.warnings.join(" ")}` : "";
  setNotice(`${data.products.source_note}。${warning}`);
  lucide.createIcons();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  setNotice("正在生成结构化方案、匹配商品、计算预算、合成视频和 Excel...");
  try {
    const data = await api("/api/run_full_pipeline", {
      method: "POST",
      body: JSON.stringify(formPayload()),
    });
    render(data);
  } catch (error) {
    setNotice(`生成失败：${error.message}`, "error");
  } finally {
    button.disabled = false;
  }
});

api("/api/health")
  .then((health) => {
    apiStatus.textContent = health.ffmpeg_available ? "在线" : "缺 FFmpeg";
    apiStatus.classList.toggle("ok", Boolean(health.ok));
  })
  .catch(() => {
    apiStatus.textContent = "离线";
  })
  .finally(() => lucide.createIcons());

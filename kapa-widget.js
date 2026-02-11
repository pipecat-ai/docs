const script = document.createElement("script");
script.src = "https://widget.kapa.ai/kapa-widget.bundle.js";
script.async = true;
script.setAttribute("data-website-id", "b1959adf-0d0a-425d-8419-5b7ff6edf937");
script.setAttribute("data-project-name", "Pipecat");
script.setAttribute("data-project-color", "#4f46e5");
script.setAttribute("data-project-logo", "https://docs.pipecat.ai/favicon.svg");
script.setAttribute(
  "data-modal-disclaimer",
  "This is a custom LLM trained on Pipecat's knowledge base to provide you with efficient access to Pipecat's capabilities and APIs. However, it may not always understand the entire context of your query to produce an accurate answer. When in doubt, please refer to our documentation or reach out on Discord."
);
script.setAttribute("data-button-bg-color", "#ffffff");
script.setAttribute("data-button-text-color", "#000000");
script.setAttribute("data-button-border", "1px solid #e5e7eb");
script.setAttribute("data-button-box-shadow", "0 0 10px rgba(0, 0, 0, 0.1)");
script.setAttribute("data-button-text-shadow", "none");
script.setAttribute("data-button-hover-bg-color", "#f3f4f6");
script.setAttribute("data-button-hover-text-color", "#000000");
script.setAttribute("data-mcp-enabled", "true");
script.setAttribute("data-mcp-server-url", "https://daily-docs.mcp.kapa.ai");
document.head.appendChild(script);

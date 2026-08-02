import { useState } from "react";
import { useAppStore } from "../../state/store";
import { useChatStream } from "../../hooks/useChatStream";

interface QuickCommand {
  name: string;
  label: string;
  description: string;
  icon: string;
}

const QUICK_COMMANDS: QuickCommand[] = [
  { name: "/build", label: "Build Tool", description: "Forge a new tool", icon: "🔧" },
  { name: "/memory", label: "Memory", description: "Search my memory", icon: "🧠" },
  { name: "/help", label: "Help", description: "Show available commands", icon: "❓" },
  { name: "/status", label: "Status", description: "Check system status", icon: "📊" },
  { name: "/shell", label: "Shell", description: "Run a command", icon: "💻" },
  { name: "/browser", label: "Browser", description: "Open web browser", icon: "🌐" },
  { name: "/search", label: "Search", description: "Search the web", icon: "🔍" },
  { name: "/trajectory", label: "Trajectory", description: "Export session data", icon: "📈" },
  { name: "/compress", label: "Compress", description: "Summarize conversation", icon: "📦" },
  { name: "/skills", label: "Skills Hub", description: "Browse community skills", icon: "🎯" },
];

export function QuickActions() {
  const [expanded, setExpanded] = useState(false);
  const { sendMessage } = useChatStream();
  const isSending = useAppStore((s) => s.isSending);

  const handleCommand = async (cmd: string) => {
    if (isSending) return;
    await sendMessage(cmd);
  };

  return (
    <div className="quick-actions-section">
      <button
        type="button"
        className="sidebar-section-header"
        onClick={() => setExpanded(!expanded)}
      >
        <span>Quick Actions</span>
        <span className={`chevron${expanded ? " expanded" : ""}`}>▼</span>
      </button>
      {expanded && (
        <div className="quick-actions-grid">
          {QUICK_COMMANDS.map((cmd) => (
            <button
              key={cmd.name}
              type="button"
              className="quick-action-btn"
              onClick={() => handleCommand(cmd.name)}
              disabled={isSending}
              title={cmd.description}
            >
              <span className="quick-action-icon">{cmd.icon}</span>
              <span className="quick-action-label">{cmd.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

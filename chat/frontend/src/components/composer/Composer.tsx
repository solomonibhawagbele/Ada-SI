import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { MAX_TEXTAREA_ROWS } from "../../constants";
import { useChatStream } from "../../hooks/useChatStream";
import { useSpeechRecognition } from "../../hooks/useSpeechRecognition";
import { useAppStore } from "../../state/store";

const DEFAULT_PLACEHOLDER = "Send a message to ADA...";
const LISTENING_PLACEHOLDER = "Listening...";

const SLASH_COMMANDS = [
  { name: "/build", description: "Forge a new tool" },
  { name: "/memory", description: "Search my memory" },
  { name: "/help", description: "Show available commands" },
  { name: "/status", description: "Check system status" },
  { name: "/shell", description: "Run a command" },
  { name: "/browser", description: "Open web browser" },
  { name: "/search", description: "Search the web" },
  { name: "/trajectory", description: "Export session data" },
  { name: "/compress", description: "Summarize conversation" },
  { name: "/skills", description: "Browse community skills" },
];

export function Composer() {
  const [input, setInput] = useState("");
  const [showSlashMenu, setShowSlashMenu] = useState(false);
  const [filteredCommands, setFilteredCommands] = useState(SLASH_COMMANDS);
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const slashMenuRef = useRef<HTMLDivElement>(null);
  const prefixRef = useRef("");
  const isSending = useAppStore((s) => s.isSending);
  const status = useAppStore((s) => s.status);
  const statusIsError = useAppStore((s) => s.statusIsError);
  const personaBootstrapActive = useAppStore((s) => s.personaBootstrapActive);
  const openSettings = useAppStore((s) => s.openSettings);
  const setStatus = useAppStore((s) => s.setStatus);
  const { sendMessage, stopGeneration } = useChatStream();
  const speech = useSpeechRecognition();

  const autoResize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 22;
    const maxHeight = lineHeight * MAX_TEXTAREA_ROWS;
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  };

  const resetTextarea = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.rows = 1;
    }
  };

  const submitContent = async (content: string) => {
    if (isSending) return;
    const trimmed = content.trim();
    if (!trimmed) return;
    setInput("");
    resetTextarea();
    setShowSlashMenu(false);
    await sendMessage(trimmed);
    textareaRef.current?.focus();
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    await submitContent(input);
  };

  const handleSlashCommandSelect = async (command: string) => {
    await submitContent(command);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (showSlashMenu) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedCommandIndex((prev) => 
          prev < filteredCommands.length - 1 ? prev + 1 : 0
        );
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedCommandIndex((prev) => 
          prev > 0 ? prev - 1 : filteredCommands.length - 1
        );
      } else if (e.key === "Enter" && filteredCommands.length > 0) {
        e.preventDefault();
        handleSlashCommandSelect(filteredCommands[selectedCommandIndex].name);
      } else if (e.key === "Escape") {
        setShowSlashMenu(false);
      }
      return;
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!isSending && !speech.isListening) {
        handleSubmit(e);
      }
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    if (speech.isListening) return;
    const value = e.target.value;
    setInput(value);

    if (value.startsWith("/")) {
      const query = value.toLowerCase();
      const filtered = SLASH_COMMANDS.filter(cmd => 
        cmd.name.toLowerCase().includes(query) || 
        cmd.description.toLowerCase().includes(query)
      );
      setFilteredCommands(filtered);
      setSelectedCommandIndex(0);
      setShowSlashMenu(filtered.length > 0);
    } else {
      setShowSlashMenu(false);
    }

    autoResize();
  };

  useEffect(() => {
    if (!speech.isListening) return;
    const combined = prefixRef.current + speech.transcript;
    setInput(combined);
    requestAnimationFrame(autoResize);
  }, [speech.isListening, speech.transcript]);

  useEffect(() => {
    if (!speech.error) return;
    setStatus(speech.error, true);
  }, [speech.error, setStatus]);

  const toggleMic = () => {
    if (isSending) return;

    if (speech.isListening) {
      speech.stop({
        onEnd: (transcript: string) => {
          const content = (prefixRef.current + transcript).trim();
          prefixRef.current = "";
          if (!content) {
            setInput("");
            resetTextarea();
            setStatus("No speech detected.", true);
            return;
          }
          submitContent(content);
        },
      });
      return;
    }

    prefixRef.current = input;
    speech.start();
  };

  const placeholder = speech.isListening ? LISTENING_PLACEHOLDER : DEFAULT_PLACEHOLDER;

  return (
    <footer className="composer">
      {personaBootstrapActive ? (
        <p className="persona-bootstrap-banner">
          Bootstrap ritual active — follow the conversation to define Scout&apos;s identity.
        </p>
      ) : null}
      
      {showSlashMenu && (
        <div className="slash-menu" ref={slashMenuRef}>
          {filteredCommands.map((cmd, index) => (
            <button
              key={cmd.name}
              type="button"
              className={`slash-menu-item${index === selectedCommandIndex ? " selected" : ""}`}
              onClick={() => handleSlashCommandSelect(cmd.name)}
            >
              <span className="slash-menu-name">{cmd.name}</span>
              <span className="slash-menu-desc">{cmd.description}</span>
            </button>
          ))}
        </div>
      )}

      <form className="composer-form" onSubmit={handleSubmit}>
        <div className="composer-input-wrap">
          <textarea
            ref={textareaRef}
            rows={1}
            placeholder={placeholder}
            value={input}
            disabled={isSending || speech.isListening}
            onChange={handleInputChange}
            onKeyDown={onKeyDown}
            required
          />
          {speech.isSupported && (
            <button
              type="button"
              className={`btn-mic${speech.isListening ? " recording" : ""}`}
              title={speech.isListening ? "Stop and send" : "Start voice input"}
              aria-label={speech.isListening ? "Stop recording and send" : "Start voice input"}
              aria-pressed={speech.isListening}
              disabled={isSending}
              onClick={toggleMic}
            >
              {speech.isListening ? (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="6" y="6" width="12" height="12" rx="1" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                  <line x1="12" y1="19" x2="12" y2="23" />
                  <line x1="8" y1="23" x2="16" y2="23" />
                </svg>
              )}
            </button>
          )}
        </div>
        <button
          type="submit"
          className={`btn-send${isSending ? " hidden" : ""}`}
          title="Launch message"
          aria-label="Launch message"
          disabled={isSending || speech.isListening}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M12 19V5M5 12l7-7 7 7" />
          </svg>
        </button>
        <button
          type="button"
          className={`btn-stop-round${isSending ? "" : " hidden"}`}
          title="Halt response"
          aria-label="Halt response"
          onClick={stopGeneration}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="6" width="12" height="12" rx="1" />
          </svg>
        </button>
      </form>
      <div className="composer-status-row">
        <p className={`status${statusIsError ? " error" : ""}`}>{status}</p>
        {statusIsError && status.toLowerCase().includes("api key") ? (
          <button
            type="button"
            className="btn-secondary btn-sm composer-api-keys-btn"
            onClick={() => openSettings("api-keys")}
          >
            Open API keys
          </button>
        ) : null}
      </div>
    </footer>
  );
}

package main

import (
	"bufio"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/joho/godotenv"
)

var (
	titleStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(lipgloss.Color("#FFB347")).
			MarginBottom(1)

	accentStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#FFD700"))

	successStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#00FF00"))

	errorStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#FF6B6B"))

	waitingStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#87CEEB"))

	dimStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#666666"))

	urlStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#00BFFF")).
			Underline(true)

	logStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#888888"))

	configStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("#DDA0DD"))
)

type Step struct {
	Name        string
	Status      string
	Description string
	LogLines    []string
	Info        string
}

type Model struct {
	steps       []Step
	spinner     spinner.Model
	currentStep int
	done        bool
	err         error
	baseDir     string
	logsDir     string
	quitting    bool
	ports       map[string]string
	config      map[string]string
	logMutex    sync.Mutex
	processes   []*exec.Cmd
}

type stepDoneMsg struct{ index int }
type stepErrorMsg struct {
	index int
	err   error
}
type logUpdateMsg struct {
	index int
	line  string
}
type configLoadedMsg struct {
	config map[string]string
}

func getEnv(key, fallback string) string {
	if value, ok := os.LookupEnv(key); ok {
		return value
	}
	return fallback
}

func initialModel(baseDir string) Model {
	s := spinner.New()
	s.Spinner = spinner.Dot
	s.Style = lipgloss.NewStyle().Foreground(lipgloss.Color("#FFD700"))

	logsDir := filepath.Join(baseDir, "logs")
	os.MkdirAll(logsDir, 0755)

	envPath := filepath.Join(baseDir, "configs", ".env")
	godotenv.Load(envPath)

	ports := map[string]string{
		"ollama":   getEnv("OLLAMA_PORT", "11434"),
		"lightrag": getEnv("LIGHTRAG_PORT", "9621"),
	}

	config := map[string]string{}

	steps := []Step{
		{Name: "Python Deps", Description: "Sync Python dependencies (uv sync)", Status: "pending"},
		{Name: "Ollama", Description: "Check/install Ollama", Status: "pending"},
		{Name: "Ollama Server", Description: "Start Ollama server", Status: "pending"},
		{Name: "Embedding Model", Description: "Pull qwen3-embedding:0.6b", Status: "pending"},
		{Name: "LightRAG", Description: "Start RAG pipeline", Status: "pending"},
		{Name: "MCP Server", Description: "Verify lightrag-mcp available", Status: "pending"},
	}

	return Model{
		steps:     steps,
		spinner:   s,
		baseDir:   baseDir,
		logsDir:   logsDir,
		ports:     ports,
		config:    config,
		processes: make([]*exec.Cmd, 0),
	}
}

func (m Model) Init() tea.Cmd {
	return tea.Batch(m.spinner.Tick, m.runStep(0))
}

func (m Model) runStep(index int) tea.Cmd {
	return func() tea.Msg {
		switch index {
		case 0:
			return m.uvSync(index)
		case 1:
			return m.checkInstallOllama(index)
		case 2:
			return m.startOllama(index)
		case 3:
			return m.pullEmbeddingModel(index)
		case 4:
			return m.startLightRAG(index)
		case 5:
			return m.verifyMCP(index)
		}
		return stepDoneMsg{index: index}
	}
}

func (m Model) uvSync(index int) tea.Msg {
	// Try with --python flag first to handle systems with multiple Python versions
	pythonVersions := []string{"3.12", "3.13", "3.11", ""}

	var lastErr error
	var lastOutput []byte

	for _, pyVer := range pythonVersions {
		var cmd *exec.Cmd
		if pyVer != "" {
			cmd = exec.Command("uv", "sync", "--python", pyVer)
		} else {
			cmd = exec.Command("uv", "sync")
		}
		cmd.Dir = m.baseDir
		output, err := cmd.CombinedOutput()
		if err == nil {
			return stepDoneMsg{index: index}
		}
		lastErr = err
		lastOutput = output
	}

	return stepErrorMsg{index: index, err: fmt.Errorf("uv sync failed: %v\n%s", lastErr, string(lastOutput))}
}

func (m Model) checkInstallOllama(index int) tea.Msg {
	_, err := exec.LookPath("ollama")
	if err == nil {
		return stepDoneMsg{index: index}
	}

	return stepErrorMsg{index: index, err: fmt.Errorf("Ollama not found. Install it from: https://ollama.ai/download")}
}

func (m Model) startOllama(index int) tea.Msg {
	healthURL := fmt.Sprintf("http://localhost:%s/api/tags", m.ports["ollama"])

	if isHealthy(healthURL) {
		return stepDoneMsg{index: index}
	}

	logFile, err := os.Create(filepath.Join(m.logsDir, "ollama.log"))
	if err != nil {
		return stepErrorMsg{index: index, err: fmt.Errorf("failed to create log file: %v", err)}
	}

	cmd := exec.Command("ollama", "serve")
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	err = cmd.Start()
	if err != nil {
		return stepErrorMsg{index: index, err: fmt.Errorf("failed to start Ollama: %v", err)}
	}

	if !waitForHealthy(healthURL, 30) {
		return stepErrorMsg{index: index, err: fmt.Errorf("Ollama failed to start (timeout)")}
	}

	return stepDoneMsg{index: index}
}

func (m Model) pullEmbeddingModel(index int) tea.Msg {
	time.Sleep(2 * time.Second)

	for i := 0; i < 3; i++ {
		cmd := exec.Command("ollama", "list")
		output, err := cmd.Output()
		if err == nil && strings.Contains(string(output), "qwen3-embedding") {
			return stepDoneMsg{index: index}
		}
		time.Sleep(1 * time.Second)
	}

	cmd := exec.Command("ollama", "pull", "qwen3-embedding:0.6b")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return stepErrorMsg{index: index, err: fmt.Errorf("failed to pull: %v - %s", err, string(output))}
	}

	return stepDoneMsg{index: index}
}

func (m *Model) startLightRAG(index int) tea.Msg {
	healthURL := fmt.Sprintf("http://localhost:%s/health", m.ports["lightrag"])

	if isHealthy(healthURL) {
		return stepDoneMsg{index: index}
	}

	// Create rag_storage directory
	ragStorageDir := filepath.Join(m.baseDir, "rag_storage")
	err := os.MkdirAll(ragStorageDir, 0755)
	if err != nil {
		return stepErrorMsg{index: index, err: fmt.Errorf("failed to create rag_storage directory: %v", err)}
	}

	logPath := filepath.Join(m.logsDir, "lightrag.log")
	logFile, err := os.Create(logPath)
	if err != nil {
		return stepErrorMsg{index: index, err: fmt.Errorf("failed to create log file: %v", err)}
	}

	cmd := exec.Command("uv", "run", "lightrag-server", "--port", m.ports["lightrag"], "--host", "127.0.0.1", "--llm-binding", "openai", "--embedding-binding", "ollama", "--working-dir", ragStorageDir)
	cmd.Dir = m.baseDir
	cmd.Stdout = logFile
	cmd.Stderr = logFile

	err = cmd.Start()
	if err != nil {
		return stepErrorMsg{index: index, err: fmt.Errorf("failed to start LightRAG: %v", err)}
	}

	if !waitForHealthy(healthURL, 60) {
		logContent := readLastLines(logPath, 5)
		return stepErrorMsg{index: index, err: fmt.Errorf("LightRAG timeout. Last logs:\n%s", logContent)}
	}

	return stepDoneMsg{index: index}
}

func (m *Model) verifyMCP(index int) tea.Msg {
	// Verify lightrag-mcp is available via uvx
	cmd := exec.Command("uvx", "lightrag-mcp", "--help")
	err := cmd.Run()
	if err != nil {
		// Try installing it
		installCmd := exec.Command("uv", "tool", "install", "lightrag-mcp")
		installOutput, installErr := installCmd.CombinedOutput()
		if installErr != nil {
			return stepErrorMsg{index: index, err: fmt.Errorf("lightrag-mcp not available: %v\n%s", installErr, string(installOutput))}
		}
	}
	return stepDoneMsg{index: index}
}

func isHealthy(url string) bool {
	client := http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == 200
}

func waitForHealthy(url string, timeoutSeconds int) bool {
	for i := 0; i < timeoutSeconds; i++ {
		if isHealthy(url) {
			return true
		}
		time.Sleep(1 * time.Second)
	}
	return false
}

func readLastLines(filePath string, n int) string {
	file, err := os.Open(filePath)
	if err != nil {
		return fmt.Sprintf("(could not read log: %v)", err)
	}
	defer file.Close()

	var lines []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
		if len(lines) > n {
			lines = lines[1:]
		}
	}
	return strings.Join(lines, "\n")
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c", "q":
			m.quitting = true
			return m, tea.Quit
		}

	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		return m, cmd

	case stepDoneMsg:
		m.steps[msg.index].Status = "done"
		m.currentStep++
		if m.currentStep >= len(m.steps) {
			m.done = true
			return m, nil
		}
		m.steps[m.currentStep].Status = "running"
		return m, m.runStep(m.currentStep)

	case stepErrorMsg:
		m.steps[msg.index].Status = "error"
		m.err = msg.err
		return m, nil

	case logUpdateMsg:
		m.logMutex.Lock()
		step := &m.steps[msg.index]
		step.LogLines = append(step.LogLines, msg.line)
		if len(step.LogLines) > 3 {
			step.LogLines = step.LogLines[len(step.LogLines)-3:]
		}
		m.logMutex.Unlock()
		return m, nil
	}

	return m, nil
}

func (m Model) View() string {
	var b strings.Builder

	accent := accentStyle.Render("🧠")
	title := titleStyle.Render(fmt.Sprintf("\n%s Engram - Memory System %s", accent, accent))
	b.WriteString(title)
	b.WriteString("\n\n")

	for i, step := range m.steps {
		var icon string
		var status string

		switch step.Status {
		case "pending":
			icon = dimStyle.Render("○")
			status = dimStyle.Render(step.Description)
		case "running":
			icon = m.spinner.View()
			status = waitingStyle.Render(step.Description + "...")
		case "done":
			icon = successStyle.Render("●")
			status = successStyle.Render(step.Description)
		case "error":
			icon = errorStyle.Render("✗")
			status = errorStyle.Render(step.Description)
		}

		line := fmt.Sprintf("  %s %s: %s", icon, step.Name, status)
		b.WriteString(line)
		b.WriteString("\n")

		if len(step.LogLines) > 0 && step.Status == "running" {
			for _, logLine := range step.LogLines {
				truncated := logLine
				if len(truncated) > 70 {
					truncated = truncated[:70] + "..."
				}
				b.WriteString(logStyle.Render(fmt.Sprintf("    │ %s\n", truncated)))
			}
		}

		if step.Status == "running" && len(step.LogLines) == 0 {
			hint := ""
			switch i {
			case 0:
				hint = "installing dependencies..."
			case 1:
				hint = "checking installation..."
			case 2:
				hint = "waiting for server..."
			case 3:
				hint = "pulling model (~639MB)..."
			case 4:
				hint = "initializing RAG..."
			case 5:
				hint = "checking lightrag-mcp..."
			}
			if hint != "" {
				b.WriteString(dimStyle.Render(fmt.Sprintf("    └─ %s\n", hint)))
			}
		}
	}

	b.WriteString("\n")

	if m.err != nil {
		b.WriteString(errorStyle.Render(fmt.Sprintf("Error: %v", m.err)))
		b.WriteString("\n\n")
		b.WriteString(dimStyle.Render("Check logs/ folder for details. Press 'q' to quit."))
	} else if m.done {
		b.WriteString(successStyle.Render("✨ Engram ready!"))
		b.WriteString("\n\n")
		b.WriteString(accentStyle.Render("  🧠 Memory system online:"))
		b.WriteString("\n\n")
		b.WriteString(fmt.Sprintf("     LightRAG API:  %s\n", urlStyle.Render(fmt.Sprintf("http://localhost:%s", m.ports["lightrag"]))))
		b.WriteString(fmt.Sprintf("     MCP Server:    %s\n", dimStyle.Render("lightrag-mcp (stdio, auto-launched by OpenCode/Claude Code)")))
		b.WriteString("\n")
		b.WriteString(dimStyle.Render("  Logs: logs/ | Press 'q' to stop"))
	} else {
		b.WriteString(dimStyle.Render("  Setting up... Press 'q' to cancel"))
	}

	b.WriteString("\n")

	return b.String()
}

func main() {
	baseDir, err := os.Getwd()
	if err != nil {
		fmt.Println("Error getting current directory:", err)
		os.Exit(1)
	}

	if _, err := os.Stat(filepath.Join(baseDir, "pyproject.toml")); os.IsNotExist(err) {
		fmt.Println("Error: Run this from the engram directory")
		fmt.Println("Expected to find: pyproject.toml")
		os.Exit(1)
	}

	p := tea.NewProgram(initialModel(baseDir))
	if _, err := p.Run(); err != nil {
		fmt.Printf("Error: %v", err)
		os.Exit(1)
	}
}

import { create } from 'zustand'
import {
  BUILD_STEPS,
  CHAT_MODEL_STORAGE_KEY,
  GEMINI_GOOGLE_SEARCH_STORAGE_KEY,
  PROGRESSION_STORAGE_KEY,
  SECOND_MODEL_STORAGE_KEY,
  THINKING_EFFORT_STORAGE_KEY,
  TTS_ENABLED_STORAGE_KEY,
  TTS_VOICE_ID_STORAGE_KEY,
  VIEWER_PHASES,
  type SettingsSection,
} from '../constants'
import { EMPTY_PROMPTS, createEmptyEffectivePrompts } from '../components/toolbar/promptSections'
import type {
  AppConfig,
  AssistantFeedItem,
  EffectivePrompts,
  FeedItem,
  PhaseStatus,
  PipPackage,
  ProcessRun,
  ProcessStep,
  ProcessStepStatus,
  PromptsConfig,
  ToolPlanCardState,
  ToolPlanFeedItem,
  ToolSummary,
  ForgeBatchState,
  ForgeBatchToolColumn,
  ForgeBatchModalMode,
} from '../types/events'
import {
  createDefaultViewerPhases,
  createToolPlanCard,
} from '../types/events'
import { createFeedId } from '../utils/id'
import {
  normalizeReasoningEffort,
  type ReasoningEffort,
} from '../utils/reasoningEffort'
import {
  didLevelUp,
  getMaxTotalXp,
  getProgression,
  xpGrantAmount,
  type ProgressionSnapshot,
  type XpSource,
} from './progression'

type SidePanelTab = 'tools' | 'packages' | 'actions'

type PromptsSaveState =
  | { status: 'idle' }
  | { status: 'saving' }
  | { status: 'saved' }
  | { status: 'error'; message: string }

export type PlayerProgress = {
  totalXp: number
  chatsCompleted: number
  skillsUnlocked: number
}

export const DEFAULT_PLAYER_PROGRESS: PlayerProgress = {
  totalXp: 0,
  chatsCompleted: 0,
  skillsUnlocked: 0,
}

export type GrantXpResult = {
  leveledUp: boolean
  xpGained: number
  progression: ProgressionSnapshot
  granted: boolean
}

export type CelebrationEvent =
  | {
      id: string
      kind: 'level'
      progression: ProgressionSnapshot
      xpGained: number
      previousLevel: number
      source: XpSource
    }
  | {
      id: string
      kind: 'skill'
      toolName: string
      progression: ProgressionSnapshot
      xpGained: number
    }

type AppState = {
  appConfig: AppConfig
  models: string[]
  chatModel: string
  toolCreatorModel: string
  thinkingEffort: ReasoningEffort
  geminiGoogleSearch: boolean
  ttsEnabled: boolean
  ttsVoiceId: string
  prompts: PromptsConfig
  effectivePrompts: EffectivePrompts
  settingsOpen: boolean
  settingsSection: SettingsSection
  promptsSaveState: PromptsSaveState
  conversation: Array<{ role: 'user' | 'assistant' | 'system'; content: string }>
  feed: FeedItem[]
  processRuns: ProcessRun[]
  activeRunId: string | null
  isSending: boolean
  status: string
  statusIsError: boolean
  activeSidePanelTab: SidePanelTab
  tools: ToolSummary[]
  packages: PipPackage[]
  showScrollBottom: boolean
  celebrations: CelebrationEvent[]
  recentlyUnlockedTool: string | null
  activeSkillApp: string | null
  skillDataRevision: number
  playerProgress: PlayerProgress
  lastXpGainAt: number | null
  abortController: AbortController | null
  runAbortControllers: Map<string, AbortController>
  forgeBatch: ForgeBatchState | null
  personaBootstrapActive: boolean
  scoutDisplayName: string

  setAppConfig: (config: AppConfig) => void
  setModels: (models: string[]) => void
  setChatModel: (model: string) => void
  setToolCreatorModel: (model: string) => void
  setThinkingEffort: (effort: ReasoningEffort) => void
  setGeminiGoogleSearch: (enabled: boolean) => void
  setTtsEnabled: (enabled: boolean) => void
  setTtsVoiceId: (voiceId: string) => void
  setPrompts: (prompts: PromptsConfig, effective: EffectivePrompts) => void
  setSettingsOpen: (open: boolean) => void
  openSettings: (section?: SettingsSection) => void
  setPromptsSaveState: (status: PromptsSaveState['status'], message?: string) => void
  setPersonaBootstrapActive: (active: boolean) => void
  setScoutDisplayName: (name: string) => void
  setStatus: (text: string, isError?: boolean) => void
  setIsSending: (active: boolean) => void
  setActiveSidePanelTab: (tab: SidePanelTab) => void
  setTools: (tools: ToolSummary[]) => void
  setPackages: (packages: PipPackage[]) => void
  setShowScrollBottom: (show: boolean) => void
  clearCelebration: () => void
  clearRecentlyUnlockedTool: () => void
  openSkillApp: (skillName: string) => void
  closeSkillApp: () => void
  bumpSkillDataRevision: () => void
  grantXp: (source: XpSource) => GrantXpResult
  resetPlayerProgress: () => void
  setAbortController: (controller: AbortController | null) => void
  bindRunAbortController: (runId: string) => AbortController
  clearRunAbortController: (runId: string) => void

  startNewChat: () => void
  addUserMessage: (content: string) => string
  addAssistantMessage: () => string
  updateAssistantMessage: (
    id: string,
    patch: Partial<
      Pick<AssistantFeedItem, 'reasoningText' | 'content' | 'streaming' | 'hidden' | 'searchSources'>
    >,
  ) => void
  removeFeedItem: (id: string) => void
  pushConversation: (message: { role: 'user' | 'assistant' | 'system'; content: string }) => void
  popConversation: () => void

  startProcessRun: (prompt: string, model: string) => string
  clearProcessRuns: () => void
  updateProcessStep: (
    runId: string,
    stepId: string,
    patch: { label: string; status: ProcessStepStatus; model?: string; detail?: string },
  ) => void
  registerBuildSteps: (runId: string) => void
  skipRemainingBuildSteps: (runId: string) => void
  stopActiveProcessStep: (runId: string, label?: string) => void
  setActiveRunId: (runId: string | null) => void

  findToolPlanByRun: (runId: string, planDraft?: boolean) => ToolPlanFeedItem | undefined
  findToolPlanByPlanId: (planId: string) => ToolPlanFeedItem | undefined
  ensureToolPlanDraft: (params: {
    runId: string
    planId?: string
    toolName?: string
    kind?: 'edit'
  }) => string
  updateToolPlanCard: (id: string, patch: Partial<ToolPlanCardState>) => void
  removeToolPlanCard: (id: string) => void
  completePlanDraft: (id: string) => void
  enterBuildingMode: (id: string, toolName: string) => void
  collapseToolPlan: (
    id: string,
    summary: string,
    status: string,
    statusClass: string,
  ) => void
  expandToolPlan: (id: string) => void
  collapseOtherToolPlans: (exceptId: string) => void
  setPipInstall: (id: string, pip: ToolPlanCardState['pipInstall']) => void
  setUiPreview: (id: string, preview: ToolPlanCardState['uiPreview']) => void
  appendViewerLog: (id: string, message: string, level?: 'info' | 'warn' | 'error') => void
  updateViewerPhase: (id: string, phaseId: string, status: PhaseStatus) => void
  showViewerSuccess: (id: string, message: string) => void

  openForgeBatchProposal: (params: {
    batchId: string
    runId: string
    summary: string
    tools: Array<{ tool_name: string; description: string; plan_id: string }>
  }) => void
  setForgeBatchModalMode: (mode: ForgeBatchModalMode) => void
  closeForgeBatch: () => void
  initForgeBatchColumns: (tools: ForgeBatchToolColumn[]) => void
  updateForgeBatchColumn: (
    planId: string,
    patch: Partial<ForgeBatchToolColumn>,
  ) => void
  findForgeBatchColumn: (planId: string) => ForgeBatchToolColumn | undefined
  showForgeBatchColumnSuccess: (planId: string, message: string) => void
}

function loadBooleanStorage(key: string): boolean {
  return localStorage.getItem(key) === 'true'
}

function loadStorage(key: string): string {
  return localStorage.getItem(key) || ''
}

function loadPlayerProgress(): PlayerProgress {
  try {
    const raw = localStorage.getItem(PROGRESSION_STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<PlayerProgress>
      return {
        totalXp: Math.max(0, Number(parsed.totalXp) || 0),
        chatsCompleted: Math.max(0, Number(parsed.chatsCompleted) || 0),
        skillsUnlocked: Math.max(0, Number(parsed.skillsUnlocked) || 0),
      }
    }
  } catch {
    // ignore corrupt storage
  }
  return { ...DEFAULT_PLAYER_PROGRESS }
}

function savePlayerProgress(progress: PlayerProgress) {
  localStorage.setItem(PROGRESSION_STORAGE_KEY, JSON.stringify(progress))
}

function migrateLegacyProgress(tools: ToolSummary[], progress: PlayerProgress): PlayerProgress {
  const hasSaved = localStorage.getItem(PROGRESSION_STORAGE_KEY) !== null
  if (hasSaved || progress.totalXp > 0 || tools.length === 0) return progress
  return {
    totalXp: Math.min(tools.length * 100, getMaxTotalXp()),
    chatsCompleted: progress.chatsCompleted,
    skillsUnlocked: tools.length,
  }
}

function createLevelUpCelebration(
  beforeXp: number,
  afterXp: number,
  xpGained: number,
  source: XpSource,
): CelebrationEvent {
  return {
    id: createFeedId(),
    kind: 'level',
    progression: getProgression(afterXp, xpGained),
    xpGained,
    previousLevel: getProgression(beforeXp).level,
    source,
  }
}

function createSkillCelebration(
  toolName: string,
  progression: ProgressionSnapshot,
  xpGained: number,
): CelebrationEvent {
  return {
    id: createFeedId(),
    kind: 'skill',
    toolName,
    progression,
    xpGained,
  }
}

function getProcessRun(runs: ProcessRun[], runId: string): ProcessRun | undefined {
  return runs.find((run) => run.runId === runId)
}

export const useAppStore = create<AppState>((set, get) => ({
  appConfig: {},
  models: [],
  chatModel: loadStorage(CHAT_MODEL_STORAGE_KEY),
  toolCreatorModel: loadStorage(SECOND_MODEL_STORAGE_KEY),
  thinkingEffort: normalizeReasoningEffort(loadStorage(THINKING_EFFORT_STORAGE_KEY)),
  geminiGoogleSearch: loadBooleanStorage(GEMINI_GOOGLE_SEARCH_STORAGE_KEY),
  ttsEnabled: loadBooleanStorage(TTS_ENABLED_STORAGE_KEY),
  ttsVoiceId: loadStorage(TTS_VOICE_ID_STORAGE_KEY),
  prompts: EMPTY_PROMPTS,
  effectivePrompts: createEmptyEffectivePrompts(),
  settingsOpen: false,
  settingsSection: 'agents',
  promptsSaveState: { status: 'idle' },
  conversation: [],
  feed: [],
  processRuns: [],
  activeRunId: null,
  isSending: false,
  status: '',
  statusIsError: false,
  activeSidePanelTab: 'tools',
  tools: [],
  packages: [],
  showScrollBottom: false,
  celebrations: [],
  recentlyUnlockedTool: null,
  activeSkillApp: null,
  skillDataRevision: 0,
  playerProgress: loadPlayerProgress(),
  lastXpGainAt: null,
  abortController: null,
  runAbortControllers: new Map(),
  forgeBatch: null,
  personaBootstrapActive: false,
  scoutDisplayName: 'ADA',

  setAppConfig: (config) => set({ appConfig: config }),
  setModels: (models) => set({ models }),
  setChatModel: (model) => {
    localStorage.setItem(CHAT_MODEL_STORAGE_KEY, model)
    set({ chatModel: model })
  },
  setToolCreatorModel: (model) => {
    localStorage.setItem(SECOND_MODEL_STORAGE_KEY, model)
    set({ toolCreatorModel: model })
  },
  setThinkingEffort: (effort) => {
    localStorage.setItem(THINKING_EFFORT_STORAGE_KEY, effort)
    set({ thinkingEffort: effort })
  },
  setGeminiGoogleSearch: (enabled) => {
    localStorage.setItem(GEMINI_GOOGLE_SEARCH_STORAGE_KEY, enabled ? 'true' : 'false')
    set({ geminiGoogleSearch: enabled })
  },
  setTtsEnabled: (enabled) => {
    localStorage.setItem(TTS_ENABLED_STORAGE_KEY, enabled ? 'true' : 'false')
    set({ ttsEnabled: enabled })
  },
  setTtsVoiceId: (voiceId) => {
    localStorage.setItem(TTS_VOICE_ID_STORAGE_KEY, voiceId)
    set({ ttsVoiceId: voiceId })
  },
  setPrompts: (prompts, effective) => set({ prompts, effectivePrompts: effective }),
  setSettingsOpen: (open) => set({ settingsOpen: open }),
  openSettings: (section = 'agents') => set({ settingsOpen: true, settingsSection: section }),
  setPromptsSaveState: (status, message = '') =>
    set({
      promptsSaveState: status === 'error' ? { status, message } : { status },
    }),
  setPersonaBootstrapActive: (active) => set({ personaBootstrapActive: active }),
  setScoutDisplayName: (name) =>
    set({ scoutDisplayName: (name || 'ADA').trim() || 'ADA' }),
  setStatus: (text, isError = false) => set({ status: text, statusIsError: isError }),
  setIsSending: (active) => set({ isSending: active }),
  setActiveSidePanelTab: (tab) => set({ activeSidePanelTab: tab }),
  setTools: (tools) => {
    const current = get().playerProgress
    const migrated = migrateLegacyProgress(tools, current)
    if (
      migrated.totalXp !== current.totalXp ||
      migrated.skillsUnlocked !== current.skillsUnlocked
    ) {
      savePlayerProgress(migrated)
      set({ tools, playerProgress: migrated })
      return
    }
    set({ tools })
  },
  setPackages: (packages) => set({ packages }),
  setShowScrollBottom: (show) => set({ showScrollBottom: show }),
  clearCelebration: () =>
    set((state) => ({
      celebrations: state.celebrations.slice(1),
    })),
  clearRecentlyUnlockedTool: () => set({ recentlyUnlockedTool: null }),
  openSkillApp: (skillName) => set({ activeSkillApp: skillName }),
  closeSkillApp: () => set({ activeSkillApp: null }),
  bumpSkillDataRevision: () =>
    set((state) => ({ skillDataRevision: state.skillDataRevision + 1 })),

  grantXp: (source) => {
    const amount = xpGrantAmount(source)
    const beforeXp = get().playerProgress.totalXp
    const progressionBefore = getProgression(beforeXp)

    if (progressionBefore.isMaxLevel) {
      return {
        leveledUp: false,
        xpGained: 0,
        progression: progressionBefore,
        granted: false,
      }
    }

    const cappedAfter = Math.min(beforeXp + amount, getMaxTotalXp())
    const xpGained = cappedAfter - beforeXp
    if (xpGained <= 0) {
      return {
        leveledUp: false,
        xpGained: 0,
        progression: progressionBefore,
        granted: false,
      }
    }

    const progress: PlayerProgress = {
      totalXp: cappedAfter,
      chatsCompleted:
        get().playerProgress.chatsCompleted + (source === 'chat' ? 1 : 0),
      skillsUnlocked:
        get().playerProgress.skillsUnlocked + (source === 'skill' ? 1 : 0),
    }
    savePlayerProgress(progress)

    const progression = getProgression(cappedAfter, xpGained)
    const leveledUp = didLevelUp(beforeXp, cappedAfter)

    set((state) => ({
      playerProgress: progress,
      lastXpGainAt: Date.now(),
      celebrations: leveledUp
        ? [
            ...state.celebrations,
            createLevelUpCelebration(beforeXp, cappedAfter, xpGained, source),
          ]
        : state.celebrations,
    }))

    return { leveledUp, xpGained, progression, granted: true }
  },

  resetPlayerProgress: () => {
    savePlayerProgress(DEFAULT_PLAYER_PROGRESS)
    set({
      playerProgress: { ...DEFAULT_PLAYER_PROGRESS },
      lastXpGainAt: null,
      celebrations: [],
      recentlyUnlockedTool: null,
      activeSkillApp: null,
    })
  },

  setAbortController: (controller) => set({ abortController: controller }),

  bindRunAbortController: (runId) => {
    const controller = new AbortController()
    const map = new Map(get().runAbortControllers)
    map.set(runId, controller)
    set({ runAbortControllers: map, abortController: controller })
    return controller
  },

  clearRunAbortController: (runId) => {
    const map = new Map(get().runAbortControllers)
    map.delete(runId)
    const current = get().abortController
    set({
      runAbortControllers: map,
      abortController: map.get(runId) === current ? null : current,
    })
  },

  startNewChat: () => {
    const { abortController, runAbortControllers } = get()
    if (abortController) abortController.abort()
    for (const controller of runAbortControllers.values()) {
      controller.abort()
    }
    set({
      conversation: [],
      feed: [],
      processRuns: [],
      activeRunId: null,
      status: '',
      statusIsError: false,
      showScrollBottom: false,
      abortController: null,
      runAbortControllers: new Map(),
    })
  },

  addUserMessage: (content) => {
    const id = createFeedId()
    set((state) => ({
      feed: [...state.feed, { id, type: 'user', content }],
    }))
    return id
  },

  addAssistantMessage: () => {
    const id = createFeedId()
    set((state) => ({
      feed: [
        ...state.feed,
        {
          id,
          type: 'assistant',
          reasoningText: '',
          content: '',
          streaming: true,
        },
      ],
    }))
    return id
  },

  updateAssistantMessage: (id, patch) => {
    set((state) => ({
      feed: state.feed.map((item) =>
        item.type === 'assistant' && item.id === id ? { ...item, ...patch } : item,
      ),
    }))
  },

  removeFeedItem: (id) => {
    set((state) => ({
      feed: state.feed.filter((item) => item.id !== id),
    }))
  },

  pushConversation: (message) => {
    set((state) => ({ conversation: [...state.conversation, message] }))
  },

  popConversation: () => {
    set((state) => ({ conversation: state.conversation.slice(0, -1) }))
  },

  startProcessRun: (prompt, model) => {
    const runId = crypto.randomUUID
      ? crypto.randomUUID().replace(/-/g, '')
      : `run${Date.now().toString(36)}`

    const initialStep: ProcessStep = {
      stepId: 'lite_model',
      label: 'Scout agent processing',
      status: 'active',
      model,
    }

    set((state) => ({
      processRuns: [
        ...state.processRuns,
        { runId, prompt, steps: [initialStep] },
      ],
      activeRunId: runId,
    }))

    return runId
  },

  clearProcessRuns: () => {
    const { runAbortControllers } = get()
    for (const controller of runAbortControllers.values()) {
      controller.abort()
    }
    set({
      processRuns: [],
      activeRunId: null,
      runAbortControllers: new Map(),
      abortController: null,
    })
  },

  updateProcessStep: (runId, stepId, patch) => {
    set((state) => ({
      processRuns: state.processRuns.map((run) => {
        if (run.runId !== runId) return run
        const existing = run.steps.find((s) => s.stepId === stepId)
        if (existing) {
          return {
            ...run,
            steps: run.steps.map((s) =>
              s.stepId === stepId ? { ...s, ...patch } : s,
            ),
          }
        }
        return {
          ...run,
          steps: [
            ...run.steps,
            { stepId, label: patch.label, status: patch.status, model: patch.model, detail: patch.detail },
          ],
        }
      }),
    }))
  },

  registerBuildSteps: (runId) => {
    for (const step of BUILD_STEPS) {
      get().updateProcessStep(runId, step.step_id, {
        label: step.label,
        status: 'pending',
      })
    }
  },

  skipRemainingBuildSteps: (runId) => {
    set((state) => ({
      processRuns: state.processRuns.map((run) => {
        if (run.runId !== runId) return run
        return {
          ...run,
          steps: run.steps.map((step) =>
            BUILD_STEPS.some((s) => s.step_id === step.stepId) &&
            step.status === 'pending'
              ? { ...step, status: 'skipped' as ProcessStepStatus }
              : step,
          ),
        }
      }),
    }))
  },

  stopActiveProcessStep: (runId, label = 'Stopped by user') => {
    const run = getProcessRun(get().processRuns, runId)
    if (!run) return
    for (const step of run.steps) {
      if (step.status === 'active') {
        get().updateProcessStep(runId, step.stepId, { label, status: 'error' })
      }
    }
    get().skipRemainingBuildSteps(runId)
  },

  setActiveRunId: (runId) => set({ activeRunId: runId }),

  findToolPlanByRun: (runId, planDraft) => {
    return get().feed.find(
      (item): item is ToolPlanFeedItem =>
        item.type === 'tool-plan' &&
        item.card.runId === runId &&
        (planDraft === undefined ||
          (planDraft
            ? item.card.mode === 'draft'
            : item.card.mode !== 'draft')),
    ) as ToolPlanFeedItem | undefined
  },

  findToolPlanByPlanId: (planId) => {
    return get().feed.find(
      (item): item is ToolPlanFeedItem =>
        item.type === 'tool-plan' && item.card.planId === planId,
    )
  },

  ensureToolPlanDraft: ({ runId, planId, toolName, kind }) => {
    const existing = get().findToolPlanByRun(runId, true)
    if (existing) {
      if (planId) {
        get().updateToolPlanCard(existing.id, { planId, toolName: toolName || existing.card.toolName, kind })
      }
      return existing.id
    }

    const id = createFeedId()
    const card = createToolPlanCard({
      id,
      runId,
      planId,
      toolName: toolName || 'Skill',
      kind,
      mode: 'draft',
    })

    set((state) => ({
      feed: [...state.feed, { id, type: 'tool-plan', card }],
    }))

    get().collapseOtherToolPlans(id)
    return id
  },

  updateToolPlanCard: (id, patch) => {
    set((state) => ({
      feed: state.feed.map((item) =>
        item.type === 'tool-plan' && item.id === id
          ? { ...item, card: { ...item.card, ...patch } }
          : item,
      ),
    }))
  },

  removeToolPlanCard: (id) => {
    set((state) => ({
      feed: state.feed.filter((item) => item.id !== id),
    }))
  },

  completePlanDraft: (id) => {
    get().updateToolPlanCard(id, { mode: 'pending' })
  },

  enterBuildingMode: (id, toolName) => {
    get().updateToolPlanCard(id, {
      mode: 'building',
      toolName,
      viewerPhases: createDefaultViewerPhases(),
      viewerOutput: [],
      codeThinking: '',
      codeStream: '',
      toolCode: '',
      testCode: '',
      codeTab: 'tool',
      codePanelTitle: 'Forging…',
      showCodeTabs: false,
      showCodeStream: true,
      showRetry: false,
      pipInstall: undefined,
    })
    get().collapseOtherToolPlans(id)
  },

  collapseToolPlan: (id, summary, status, statusClass) => {
    get().updateToolPlanCard(id, {
      mode: 'collapsed',
      collapsedSummary: summary,
      collapsedStatus: status,
      collapsedStatusClass: statusClass,
      busy: false,
    })
  },

  expandToolPlan: (id) => {
    const item = get().feed.find((f) => f.id === id && f.type === 'tool-plan') as
      | ToolPlanFeedItem
      | undefined
    if (!item) return
    const nextMode = item.card.lastSuccessMessage ? 'success' : 'building'
    get().updateToolPlanCard(id, { mode: nextMode })
    get().collapseOtherToolPlans(id)
  },

  collapseOtherToolPlans: (exceptId) => {
    const state = get()
    for (const item of state.feed) {
      if (item.type !== 'tool-plan' || item.id === exceptId) continue
      const { card } = item
      if (card.mode === 'collapsed') continue
      if (card.mode === 'success' || card.lastSuccessMessage) {
        get().collapseToolPlan(
          item.id,
          card.lastSuccessMessage || '',
          'Unlocked',
          'success',
        )
      } else if (card.mode === 'pending') {
        get().collapseToolPlan(item.id, '', 'Blueprint pending', 'pending')
      }
    }
  },

  setPipInstall: (id, pip) => {
    get().updateToolPlanCard(id, { pipInstall: pip })
  },

  setUiPreview: (id, preview) => {
    get().updateToolPlanCard(id, { uiPreview: preview })
  },

  appendViewerLog: (id, message, level = 'info') => {
    const item = get().feed.find((f) => f.id === id && f.type === 'tool-plan') as
      | ToolPlanFeedItem
      | undefined
    if (!item) return
    const prefix = level === 'error' ? '[ERROR] ' : level === 'warn' ? '[WARN] ' : ''
    get().updateToolPlanCard(id, {
      viewerOutput: [...item.card.viewerOutput, `${prefix}${message}`],
      codeTab: level === 'error' ? 'output' : item.card.codeTab,
      showCodeTabs: level === 'error' ? true : item.card.showCodeTabs,
    })
  },

  updateViewerPhase: (id, phaseId, status) => {
    const item = get().feed.find((f) => f.id === id && f.type === 'tool-plan') as
      | ToolPlanFeedItem
      | undefined
    if (!item) return
    get().updateToolPlanCard(id, {
      viewerPhases: { ...item.card.viewerPhases, [phaseId]: status },
    })
  },

  showViewerSuccess: (id, message) => {
    const item = get().feed.find((f) => f.id === id && f.type === 'tool-plan') as
      | ToolPlanFeedItem
      | undefined
    const toolName = item?.card.toolName || 'Skill'
    const xpResult = get().grantXp('skill')

    const phases = Object.fromEntries(
      VIEWER_PHASES.map((p) => [p.id, 'done' as PhaseStatus]),
    )
    get().updateToolPlanCard(id, {
      viewerPhases: phases,
      viewerOutput: [...item?.card.viewerOutput || [], message],
      codePanelTitle: 'Forge complete',
      codeTab: 'output',
      showCodeTabs: true,
      showRetry: false,
      lastSuccessMessage: message,
      mode: 'success',
      busy: false,
    })

    set((state) => ({
      celebrations: [
        ...state.celebrations,
        createSkillCelebration(toolName, xpResult.progression, xpResult.xpGained),
      ],
      recentlyUnlockedTool: toolName,
      activeSidePanelTab: 'tools',
    }))

    window.setTimeout(() => {
      const current = get().feed.find((f) => f.id === id && f.type === 'tool-plan') as
        | ToolPlanFeedItem
        | undefined
      if (!current || current.card.mode !== 'success') return
      get().collapseToolPlan(id, message, 'Unlocked', 'success')
    }, 2800)
  },

  openForgeBatchProposal: ({ batchId, runId, summary, tools }) => {
    set({
      forgeBatch: {
        batchId,
        runId,
        summary,
        modalMode: 'confirming',
        proposedTools: tools,
        tools: [],
      },
    })
  },

  setForgeBatchModalMode: (mode) => {
    const batch = get().forgeBatch
    if (!batch) return
    set({ forgeBatch: { ...batch, modalMode: mode } })
  },

  closeForgeBatch: () => set({ forgeBatch: null }),

  initForgeBatchColumns: (tools) => {
    const batch = get().forgeBatch
    if (!batch) return
    set({
      forgeBatch: {
        ...batch,
        tools,
        modalMode: 'expanded',
      },
    })
  },

  updateForgeBatchColumn: (planId, patch) => {
    const batch = get().forgeBatch
    if (!batch) return
    set({
      forgeBatch: {
        ...batch,
        tools: batch.tools.map((col) =>
          col.planId === planId ? { ...col, ...patch } : col,
        ),
      },
    })
  },

  findForgeBatchColumn: (planId) => {
    return get().forgeBatch?.tools.find((col) => col.planId === planId)
  },

  showForgeBatchColumnSuccess: (planId, message) => {
    const col = get().findForgeBatchColumn(planId)
    if (!col) return
    const xpResult = get().grantXp('skill')
    get().updateForgeBatchColumn(planId, {
      status: 'done',
      lastSuccessMessage: message,
      busy: false,
      viewerPhases: Object.fromEntries(
        VIEWER_PHASES.map((p) => [p.id, 'done' as PhaseStatus]),
      ),
      viewerOutput: [...col.viewerOutput, message],
    })
    set((state) => ({
      celebrations: [
        ...state.celebrations,
        createSkillCelebration(col.toolName, xpResult.progression, xpResult.xpGained),
      ],
      recentlyUnlockedTool: col.toolName,
      activeSidePanelTab: 'tools',
    }))
  },
}))

export function buildMessages(): Array<{ role: string; content: string }> {
  return [...useAppStore.getState().conversation]
}

export function runHasActiveStep(runId: string): boolean {
  const run = getProcessRun(useAppStore.getState().processRuns, runId)
  return run?.steps.some((s) => s.status === 'active') ?? false
}

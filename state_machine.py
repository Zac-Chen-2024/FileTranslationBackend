"""
翻译平台状态机定义

完整的状态转换系统，支持：
- 分支转换（基于条件选择不同路径）
- 跳过转换（某些步骤可选）
- 回退转换（重新翻译、旋转等）
- 重置转换（清空中间状态）

状态流程图：

  ┌─────────┐     ┌──────────┐     ┌─────────────┐
  │ uploaded │────►│ splitting │────►│split_complete│
  └────┬────┘     └──────────┘     └──────┬──────┘
       │                                   │
       └───────────────┬───────────────────┘
                       ▼
                ┌─────────────┐
                │ translating │
                └──────┬──────┘
                       │
              ┌────────┴────────┐
              ▼                 ▼
        ┌──────────┐      ┌─────────┐
        │translated │      │ failed  │
        └────┬─────┘      └────┬────┘
             │                 │
    ┌────────┼─────────┐       │ (重试)
    │        │         │       │
    ▼        ▼         ▼       │
 [直接   [实体识别  [LLM优化   │
  确认]   流程]      流程]     │
    │        │         │       │
    │        ▼         │       │
    │  ┌────────────┐  │       │
    │  │entity_     │  │       │
    │  │recognizing │  │       │
    │  └─────┬──────┘  │       │
    │        │         │       │
    │        ▼         │       │
    │  ┌────────────┐  │       │
    │  │entity_     │◄─┼───────┘
    │  │pending_    │  │
    │  │confirm     │  │
    │  └─────┬──────┘  │
    │        │         │
    │        ▼         │
    │  ┌────────────┐  │
    │  │entity_     │  │
    │  │confirmed   │  │
    │  └─────┬──────┘  │
    │        │         │
    │        └────┬────┘
    │             ▼
    │      ┌────────────┐
    │      │llm_        │
    │      │translating │
    │      └─────┬──────┘
    │            │
    │            ▼
    │      ┌────────────┐
    │      │llm_        │
    │      │translated  │
    │      └─────┬──────┘
    │            │
    └──────┬─────┘
           ▼
     ┌───────────┐
     │ confirmed │
     └───────────┘

"""

from enum import Enum
from typing import Optional, List, Dict, Set, Callable
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


class ProcessingStep(str, Enum):
    """处理步骤枚举 - 状态机的所有状态"""

    # === 上传阶段 ===
    UPLOADED = 'uploaded'              # 已上传，等待处理
    SPLITTING = 'splitting'            # PDF拆分中
    SPLIT_COMPLETED = 'split_completed'  # PDF拆分完成

    # === OCR翻译阶段 ===
    TRANSLATING = 'translating'        # 翻译中（百度API）
    TRANSLATED = 'translated'          # 翻译完成

    # === 实体识别阶段（可选流程）===
    ENTITY_RECOGNIZING = 'entity_recognizing'        # 实体识别中
    ENTITY_PENDING_CONFIRM = 'entity_pending_confirm'  # 等待用户确认实体（卡关点）
    ENTITY_CONFIRMED = 'entity_confirmed'            # 实体已确认

    # === LLM优化阶段（可选流程）===
    LLM_TRANSLATING = 'llm_translating'  # LLM优化中
    LLM_TRANSLATED = 'llm_translated'    # LLM优化完成

    # === 最终状态 ===
    CONFIRMED = 'confirmed'            # 用户已确认完成
    FAILED = 'failed'                  # 处理失败


class TransitionType(str, Enum):
    """转换类型"""
    NORMAL = 'normal'           # 正常转换
    SKIP = 'skip'               # 跳过转换
    RESET = 'reset'             # 重置转换（清空中间状态）
    RETRY = 'retry'             # 重试转换
    AUTO = 'auto'               # 自动转换（后台触发）
    ROLLBACK = 'rollback'       # 回退转换


@dataclass
class StateTransition:
    """状态转换定义"""
    from_states: Set[ProcessingStep]   # 允许的源状态
    to_state: ProcessingStep           # 目标状态
    transition_type: TransitionType    # 转换类型
    trigger: str                       # 触发动作（API或事件）
    condition: Optional[str] = None    # 转换条件描述
    clears_data: bool = False          # 是否清除中间数据
    auto_next: Optional[ProcessingStep] = None  # 自动触发的下一个状态


# ============================================================
# 状态转换规则定义
# ============================================================

STATE_TRANSITIONS: Dict[str, StateTransition] = {

    # === 上传阶段 ===
    'upload_image': StateTransition(
        from_states={None},  # 新建
        to_state=ProcessingStep.UPLOADED,
        transition_type=TransitionType.NORMAL,
        trigger='POST /api/clients/<id>/materials/upload (image)',
        condition='单张图片上传',
    ),

    'upload_pdf': StateTransition(
        from_states={None},  # 新建
        to_state=ProcessingStep.SPLITTING,
        transition_type=TransitionType.NORMAL,
        trigger='POST /api/clients/<id>/materials/upload (pdf)',
        condition='PDF文件上传',
    ),

    'split_complete': StateTransition(
        from_states={ProcessingStep.SPLITTING},
        to_state=ProcessingStep.SPLIT_COMPLETED,
        transition_type=TransitionType.AUTO,
        trigger='后台拆分线程完成',
        condition='PDF单页转换完成',
    ),

    # === 翻译阶段 ===
    'start_translate': StateTransition(
        from_states={
            ProcessingStep.UPLOADED,
            ProcessingStep.SPLIT_COMPLETED,
        },
        to_state=ProcessingStep.TRANSLATING,
        transition_type=TransitionType.NORMAL,
        trigger='POST /api/clients/<id>/materials/translate',
        condition='用户点击翻译',
    ),

    'translate_success': StateTransition(
        from_states={ProcessingStep.TRANSLATING},
        to_state=ProcessingStep.TRANSLATED,
        transition_type=TransitionType.AUTO,
        trigger='百度API返回成功',
        condition='识别到文字区域',
    ),

    'translate_fail': StateTransition(
        from_states={ProcessingStep.TRANSLATING},
        to_state=ProcessingStep.FAILED,
        transition_type=TransitionType.AUTO,
        trigger='百度API返回失败',
        condition='API错误或无文字',
    ),

    # === 实体识别阶段（可选）===
    'start_entity_recognition': StateTransition(
        from_states={ProcessingStep.TRANSLATED},
        to_state=ProcessingStep.ENTITY_RECOGNIZING,
        transition_type=TransitionType.NORMAL,
        trigger='POST /api/materials/<id>/entity-recognition',
        condition='启用实体识别且用户触发',
    ),

    'entity_recognition_success': StateTransition(
        from_states={ProcessingStep.ENTITY_RECOGNIZING},
        to_state=ProcessingStep.ENTITY_PENDING_CONFIRM,
        transition_type=TransitionType.AUTO,
        trigger='实体识别服务返回成功',
        condition='识别到实体列表',
    ),

    'entity_recognition_skip': StateTransition(
        from_states={ProcessingStep.ENTITY_RECOGNIZING},
        to_state=ProcessingStep.TRANSLATED,
        transition_type=TransitionType.SKIP,
        trigger='实体识别服务返回可恢复错误',
        condition='recoverable=true，跳过实体识别',
    ),

    'entity_recognition_fail': StateTransition(
        from_states={ProcessingStep.ENTITY_RECOGNIZING},
        to_state=ProcessingStep.FAILED,
        transition_type=TransitionType.AUTO,
        trigger='实体识别服务返回不可恢复错误',
        condition='recoverable=false',
    ),

    'confirm_entities': StateTransition(
        from_states={ProcessingStep.ENTITY_PENDING_CONFIRM},
        to_state=ProcessingStep.ENTITY_CONFIRMED,
        transition_type=TransitionType.NORMAL,
        trigger='POST /api/materials/<id>/confirm-entities',
        condition='用户确认实体编辑',
        auto_next=ProcessingStep.LLM_TRANSLATING,  # 自动触发LLM
    ),

    # === LLM优化阶段（可选）===
    'start_llm_from_entity': StateTransition(
        from_states={ProcessingStep.ENTITY_CONFIRMED},
        to_state=ProcessingStep.LLM_TRANSLATING,
        transition_type=TransitionType.AUTO,
        trigger='confirm_entities后台线程自动触发',
        condition='实体确认后自动执行',
    ),

    'start_llm_manual': StateTransition(
        from_states={ProcessingStep.TRANSLATED},
        to_state=ProcessingStep.LLM_TRANSLATING,
        transition_type=TransitionType.NORMAL,
        trigger='POST /api/materials/<id>/llm-translate',
        condition='未启用实体识别时手动触发',
    ),

    'llm_success': StateTransition(
        from_states={ProcessingStep.LLM_TRANSLATING},
        to_state=ProcessingStep.LLM_TRANSLATED,
        transition_type=TransitionType.AUTO,
        trigger='LLM服务返回成功',
        condition='优化结果生成',
    ),

    'llm_fail': StateTransition(
        from_states={ProcessingStep.LLM_TRANSLATING},
        to_state=ProcessingStep.FAILED,
        transition_type=TransitionType.AUTO,
        trigger='LLM服务返回失败',
        condition='LLM服务异常',
    ),

    # === 确认阶段 ===
    'confirm_from_translated': StateTransition(
        from_states={ProcessingStep.TRANSLATED},
        to_state=ProcessingStep.CONFIRMED,
        transition_type=TransitionType.NORMAL,
        trigger='POST /api/materials/<id>/confirm',
        condition='跳过实体识别和LLM，直接确认',
    ),

    'confirm_from_llm': StateTransition(
        from_states={ProcessingStep.LLM_TRANSLATED},
        to_state=ProcessingStep.CONFIRMED,
        transition_type=TransitionType.NORMAL,
        trigger='POST /api/materials/<id>/confirm',
        condition='LLM优化后确认',
    ),

    'unconfirm_to_translated': StateTransition(
        from_states={ProcessingStep.CONFIRMED},
        to_state=ProcessingStep.TRANSLATED,
        transition_type=TransitionType.ROLLBACK,
        trigger='POST /api/materials/<id>/unconfirm',
        condition='取消确认（无LLM结果时）',
    ),

    'unconfirm_to_llm': StateTransition(
        from_states={ProcessingStep.CONFIRMED},
        to_state=ProcessingStep.LLM_TRANSLATED,
        transition_type=TransitionType.ROLLBACK,
        trigger='POST /api/materials/<id>/unconfirm',
        condition='取消确认（有LLM结果时）',
    ),

    # === 重置/重试阶段 ===
    'retranslate': StateTransition(
        from_states={
            ProcessingStep.TRANSLATED,
            ProcessingStep.ENTITY_PENDING_CONFIRM,
            ProcessingStep.ENTITY_CONFIRMED,
            ProcessingStep.LLM_TRANSLATED,
            ProcessingStep.CONFIRMED,
            ProcessingStep.FAILED,
        },
        to_state=ProcessingStep.TRANSLATING,
        transition_type=TransitionType.RETRY,
        trigger='POST /api/materials/<id>/retranslate',
        condition='重新翻译',
        clears_data=True,
    ),

    'rotate_reset': StateTransition(
        from_states={
            ProcessingStep.UPLOADED,
            ProcessingStep.SPLIT_COMPLETED,
            ProcessingStep.TRANSLATED,
            ProcessingStep.ENTITY_RECOGNIZING,
            ProcessingStep.ENTITY_PENDING_CONFIRM,
            ProcessingStep.ENTITY_CONFIRMED,
            ProcessingStep.LLM_TRANSLATING,
            ProcessingStep.LLM_TRANSLATED,
            ProcessingStep.CONFIRMED,
            ProcessingStep.FAILED,
        },
        to_state=ProcessingStep.UPLOADED,
        transition_type=TransitionType.RESET,
        trigger='POST /api/materials/<id>/rotate',
        condition='旋转图片，完全重置',
        clears_data=True,
    ),

    'retry_from_failed': StateTransition(
        from_states={ProcessingStep.FAILED},
        to_state=ProcessingStep.TRANSLATING,
        transition_type=TransitionType.RETRY,
        trigger='POST /api/materials/<id>/retranslate',
        condition='从失败状态重试',
        clears_data=True,
    ),
}


# ============================================================
# 状态显示映射
# ============================================================

STATUS_DISPLAY: Dict[str, str] = {
    ProcessingStep.UPLOADED.value: '已上传',
    ProcessingStep.SPLITTING.value: '拆分中',
    ProcessingStep.SPLIT_COMPLETED.value: '拆分完成',
    ProcessingStep.TRANSLATING.value: '翻译中',
    ProcessingStep.TRANSLATED.value: '翻译完成',
    ProcessingStep.ENTITY_RECOGNIZING.value: '实体识别中',
    ProcessingStep.ENTITY_PENDING_CONFIRM.value: '待确认实体',
    ProcessingStep.ENTITY_CONFIRMED.value: '实体已确认',
    ProcessingStep.LLM_TRANSLATING.value: 'AI优化中',
    ProcessingStep.LLM_TRANSLATED.value: 'AI优化完成',
    ProcessingStep.CONFIRMED.value: '已确认',
    ProcessingStep.FAILED.value: '处理失败',
}

# 旧状态值映射（向后兼容）
LEGACY_STATUS_MAP: Dict[str, str] = {
    '待处理': ProcessingStep.UPLOADED.value,
    '已上传': ProcessingStep.UPLOADED.value,
    '已添加': ProcessingStep.UPLOADED.value,
    '拆分中': ProcessingStep.SPLITTING.value,
    '翻译中': ProcessingStep.TRANSLATING.value,
    '正在翻译': ProcessingStep.TRANSLATING.value,
    '处理中': ProcessingStep.TRANSLATING.value,
    '翻译完成': ProcessingStep.TRANSLATED.value,
    '已翻译': ProcessingStep.TRANSLATED.value,
    '翻译失败': ProcessingStep.FAILED.value,
    '已确认': ProcessingStep.CONFIRMED.value,
    'AI优化中': ProcessingStep.LLM_TRANSLATING.value,
    'AI优化完成': ProcessingStep.LLM_TRANSLATED.value,
}


# ============================================================
# 状态颜色配置（用于前端）
# ============================================================

STATUS_COLORS: Dict[str, Dict] = {
    ProcessingStep.UPLOADED.value: {'bg': '#e3f2fd', 'text': '#1976d2', 'label': 'info'},
    ProcessingStep.SPLITTING.value: {'bg': '#fff3e0', 'text': '#f57c00', 'label': 'warning'},
    ProcessingStep.SPLIT_COMPLETED.value: {'bg': '#e8f5e9', 'text': '#388e3c', 'label': 'success'},
    ProcessingStep.TRANSLATING.value: {'bg': '#fff3e0', 'text': '#f57c00', 'label': 'warning'},
    ProcessingStep.TRANSLATED.value: {'bg': '#e8f5e9', 'text': '#388e3c', 'label': 'success'},
    ProcessingStep.ENTITY_RECOGNIZING.value: {'bg': '#f3e5f5', 'text': '#7b1fa2', 'label': 'processing'},
    ProcessingStep.ENTITY_PENDING_CONFIRM.value: {'bg': '#fff8e1', 'text': '#ff8f00', 'label': 'pending'},
    ProcessingStep.ENTITY_CONFIRMED.value: {'bg': '#e8f5e9', 'text': '#388e3c', 'label': 'success'},
    ProcessingStep.LLM_TRANSLATING.value: {'bg': '#e8eaf6', 'text': '#3f51b5', 'label': 'processing'},
    ProcessingStep.LLM_TRANSLATED.value: {'bg': '#e8f5e9', 'text': '#388e3c', 'label': 'success'},
    ProcessingStep.CONFIRMED.value: {'bg': '#e8f5e9', 'text': '#2e7d32', 'label': 'confirmed'},
    ProcessingStep.FAILED.value: {'bg': '#ffebee', 'text': '#c62828', 'label': 'error'},
}


# ============================================================
# 状态分类
# ============================================================

# 处理中状态（显示loading）
PROCESSING_STATES: Set[ProcessingStep] = {
    ProcessingStep.SPLITTING,
    ProcessingStep.TRANSLATING,
    ProcessingStep.ENTITY_RECOGNIZING,
    ProcessingStep.LLM_TRANSLATING,
}

# 等待用户操作状态（卡关点）
PENDING_ACTION_STATES: Set[ProcessingStep] = {
    ProcessingStep.UPLOADED,
    ProcessingStep.SPLIT_COMPLETED,
    ProcessingStep.ENTITY_PENDING_CONFIRM,  # 关键卡关点
}

# 完成状态（可确认）
COMPLETED_STATES: Set[ProcessingStep] = {
    ProcessingStep.TRANSLATED,
    ProcessingStep.ENTITY_CONFIRMED,
    ProcessingStep.LLM_TRANSLATED,
    ProcessingStep.CONFIRMED,
}

# 可跳过的状态
SKIPPABLE_STATES: Set[ProcessingStep] = {
    ProcessingStep.ENTITY_RECOGNIZING,
    ProcessingStep.ENTITY_PENDING_CONFIRM,
    ProcessingStep.ENTITY_CONFIRMED,
    ProcessingStep.LLM_TRANSLATING,
    ProcessingStep.LLM_TRANSLATED,
}


# ============================================================
# 状态转换验证器
# ============================================================

class StateTransitionError(Exception):
    """状态转换错误"""
    def __init__(self, message: str, current_state: str, target_state: str, transition: str = None):
        self.current_state = current_state
        self.target_state = target_state
        self.transition = transition
        super().__init__(message)


class StateMachine:
    """状态机管理器"""

    @staticmethod
    def normalize_state(state: str) -> Optional[str]:
        """
        标准化状态值
        将旧的中文状态映射到新的枚举值
        """
        if state is None:
            return None

        # 已经是标准枚举值
        try:
            ProcessingStep(state)
            return state
        except ValueError:
            pass

        # 尝试从旧状态映射
        if state in LEGACY_STATUS_MAP:
            return LEGACY_STATUS_MAP[state]

        # 未知状态
        logger.warning(f"Unknown state value: {state}")
        return state

    @staticmethod
    def get_display(step: str) -> str:
        """获取状态的中文显示"""
        normalized = StateMachine.normalize_state(step)
        return STATUS_DISPLAY.get(normalized, step or '未知')

    @staticmethod
    def get_color(step: str) -> Dict:
        """获取状态的颜色配置"""
        normalized = StateMachine.normalize_state(step)
        return STATUS_COLORS.get(normalized, {'bg': '#f5f5f5', 'text': '#757575', 'label': 'default'})

    @staticmethod
    def is_processing(step: str) -> bool:
        """判断是否为处理中状态"""
        normalized = StateMachine.normalize_state(step)
        try:
            return ProcessingStep(normalized) in PROCESSING_STATES
        except (ValueError, TypeError):
            return False

    @staticmethod
    def is_pending_action(step: str) -> bool:
        """判断是否为等待用户操作状态"""
        normalized = StateMachine.normalize_state(step)
        try:
            return ProcessingStep(normalized) in PENDING_ACTION_STATES
        except (ValueError, TypeError):
            return False

    @staticmethod
    def is_completed(step: str) -> bool:
        """判断是否为完成状态"""
        normalized = StateMachine.normalize_state(step)
        try:
            return ProcessingStep(normalized) in COMPLETED_STATES
        except (ValueError, TypeError):
            return False

    @staticmethod
    def is_failed(step: str) -> bool:
        """判断是否为失败状态"""
        normalized = StateMachine.normalize_state(step)
        return normalized == ProcessingStep.FAILED.value

    @staticmethod
    def is_skippable(step: str) -> bool:
        """判断是否为可跳过状态"""
        normalized = StateMachine.normalize_state(step)
        try:
            return ProcessingStep(normalized) in SKIPPABLE_STATES
        except (ValueError, TypeError):
            return False

    @staticmethod
    def can_transition(current_state: str, target_state: str) -> bool:
        """
        检查是否可以从当前状态转换到目标状态
        """
        normalized_current = StateMachine.normalize_state(current_state)
        normalized_target = StateMachine.normalize_state(target_state)

        for transition in STATE_TRANSITIONS.values():
            if transition.to_state.value == normalized_target:
                # 检查源状态是否匹配
                if normalized_current is None and None in transition.from_states:
                    return True
                try:
                    current_step = ProcessingStep(normalized_current) if normalized_current else None
                    if current_step in transition.from_states:
                        return True
                except (ValueError, TypeError):
                    pass

        return False

    @staticmethod
    def get_valid_transitions(current_state: str) -> List[Dict]:
        """
        获取当前状态可用的所有转换
        """
        normalized = StateMachine.normalize_state(current_state)
        valid = []

        try:
            current_step = ProcessingStep(normalized) if normalized else None
        except (ValueError, TypeError):
            return valid

        for name, transition in STATE_TRANSITIONS.items():
            if current_step in transition.from_states or (current_step is None and None in transition.from_states):
                valid.append({
                    'name': name,
                    'to_state': transition.to_state.value,
                    'to_display': STATUS_DISPLAY.get(transition.to_state.value),
                    'type': transition.transition_type.value,
                    'trigger': transition.trigger,
                    'condition': transition.condition,
                })

        return valid

    @staticmethod
    def validate_transition(current_state: str, target_state: str, transition_name: str = None) -> StateTransition:
        """
        验证状态转换是否有效

        Args:
            current_state: 当前状态
            target_state: 目标状态
            transition_name: 可选，指定转换名称

        Returns:
            StateTransition: 匹配的转换定义

        Raises:
            StateTransitionError: 转换无效时
        """
        normalized_current = StateMachine.normalize_state(current_state)
        normalized_target = StateMachine.normalize_state(target_state)

        try:
            current_step = ProcessingStep(normalized_current) if normalized_current else None
        except (ValueError, TypeError):
            raise StateTransitionError(
                f"Invalid current state: {current_state}",
                current_state, target_state
            )

        try:
            target_step = ProcessingStep(normalized_target)
        except (ValueError, TypeError):
            raise StateTransitionError(
                f"Invalid target state: {target_state}",
                current_state, target_state
            )

        # 如果指定了转换名称，直接查找
        if transition_name and transition_name in STATE_TRANSITIONS:
            transition = STATE_TRANSITIONS[transition_name]
            if current_step in transition.from_states and transition.to_state == target_step:
                return transition
            raise StateTransitionError(
                f"Transition '{transition_name}' not valid from {current_state} to {target_state}",
                current_state, target_state, transition_name
            )

        # 查找匹配的转换
        for name, transition in STATE_TRANSITIONS.items():
            if transition.to_state == target_step and current_step in transition.from_states:
                return transition

        # 没有找到有效转换
        valid_targets = [t.to_state.value for t in STATE_TRANSITIONS.values() if current_step in t.from_states]
        raise StateTransitionError(
            f"Cannot transition from '{current_state}' to '{target_state}'. "
            f"Valid targets: {valid_targets}",
            current_state, target_state
        )

    @staticmethod
    def execute_transition(material, target_state: str, transition_name: str = None) -> Dict:
        """
        执行状态转换（用于Material模型）

        Args:
            material: Material对象
            target_state: 目标状态
            transition_name: 可选，指定转换名称

        Returns:
            dict: 包含转换结果的字典
        """
        current_state = material.processing_step

        # 验证转换
        transition = StateMachine.validate_transition(current_state, target_state, transition_name)

        # 记录转换日志
        logger.info(
            f"State transition: Material {material.id} "
            f"[{current_state}] -> [{target_state}] "
            f"(type: {transition.transition_type.value})"
        )

        # 更新状态
        old_state = current_state
        material.processing_step = target_state
        material.status = STATUS_DISPLAY.get(target_state, target_state)

        result = {
            'success': True,
            'old_state': old_state,
            'new_state': target_state,
            'transition_type': transition.transition_type.value,
            'clears_data': transition.clears_data,
            'auto_next': transition.auto_next.value if transition.auto_next else None,
        }

        return result


# ============================================================
# 辅助函数（向后兼容）
# ============================================================

def get_status_display(step: str) -> str:
    """获取状态的中文显示（向后兼容）"""
    return StateMachine.get_display(step)


def get_legacy_status(step: str) -> str:
    """
    获取旧的中文状态值（向后兼容）
    用于status字段
    """
    return StateMachine.get_display(step)


def is_processing(step: str) -> bool:
    """判断是否为处理中状态（向后兼容）"""
    return StateMachine.is_processing(step)


def is_pending_action(step: str) -> bool:
    """判断是否为等待用户操作状态（向后兼容）"""
    return StateMachine.is_pending_action(step)


def is_completed(step: str) -> bool:
    """判断是否为完成状态（向后兼容）"""
    return StateMachine.is_completed(step)


def is_failed(step: str) -> bool:
    """判断是否为失败状态（向后兼容）"""
    return StateMachine.is_failed(step)


# ============================================================
# 流程定义（用于前端显示）
# ============================================================

WORKFLOW_PATHS = {
    'simple': {
        'name': '简单流程',
        'description': '上传 → 翻译 → 确认',
        'steps': [
            ProcessingStep.UPLOADED,
            ProcessingStep.TRANSLATING,
            ProcessingStep.TRANSLATED,
            ProcessingStep.CONFIRMED,
        ],
    },
    'with_llm': {
        'name': 'AI优化流程',
        'description': '上传 → 翻译 → AI优化 → 确认',
        'steps': [
            ProcessingStep.UPLOADED,
            ProcessingStep.TRANSLATING,
            ProcessingStep.TRANSLATED,
            ProcessingStep.LLM_TRANSLATING,
            ProcessingStep.LLM_TRANSLATED,
            ProcessingStep.CONFIRMED,
        ],
    },
    'with_entity': {
        'name': '实体识别流程',
        'description': '上传 → 翻译 → 实体识别 → 确认实体 → AI优化 → 确认',
        'steps': [
            ProcessingStep.UPLOADED,
            ProcessingStep.TRANSLATING,
            ProcessingStep.TRANSLATED,
            ProcessingStep.ENTITY_RECOGNIZING,
            ProcessingStep.ENTITY_PENDING_CONFIRM,
            ProcessingStep.ENTITY_CONFIRMED,
            ProcessingStep.LLM_TRANSLATING,
            ProcessingStep.LLM_TRANSLATED,
            ProcessingStep.CONFIRMED,
        ],
    },
    'pdf': {
        'name': 'PDF流程',
        'description': '上传PDF → 拆分 → 翻译 → 确认',
        'steps': [
            ProcessingStep.SPLITTING,
            ProcessingStep.SPLIT_COMPLETED,
            ProcessingStep.TRANSLATING,
            ProcessingStep.TRANSLATED,
            ProcessingStep.CONFIRMED,
        ],
    },
}

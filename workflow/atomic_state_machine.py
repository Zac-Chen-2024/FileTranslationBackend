# -*- coding: utf-8 -*-
"""
原子化状态机 - 管理翻译流程的状态转换

设计原则：
1. 每个操作都是原子的，可独立调用
2. 状态转换必须通过验证
3. 支持灵活的流程组合

状态流程图：
```
                    ┌─────────┐
                    │ uploaded │
                    └────┬────┘
                         │ translate_baidu
                         ▼
                   ┌───────────┐
                   │ translated │
                   └─────┬─────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
  entity_recognize   llm_optimize   skip_to_review
         │               │               │
         ▼               │               │
┌────────────────┐       │               │
│entity_pending_ │       │               │
│    confirm     │       │               │
└───────┬────────┘       │               │
        │                │               │
        ▼                │               │
  entity_confirm         │               │
        │                │               │
        ▼                │               │
┌────────────────┐       │               │
│entity_confirmed│       │               │
└───────┬────────┘       │               │
        │                │               │
        ├────────────────┘               │
        │ llm_optimize                   │
        ▼                                │
┌────────────────┐                       │
│ llm_translated │                       │
└───────┬────────┘                       │
        │                                │
        ├────────────────────────────────┘
        │ review
        ▼
  ┌───────────┐
  │ confirmed │
  └───────────┘
```
"""

from typing import List, Dict, Optional, Set
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ProcessingStep(str, Enum):
    """处理步骤枚举"""
    # 上传阶段
    UPLOADED = 'uploaded'
    SPLITTING = 'splitting'
    SPLIT_COMPLETED = 'split_completed'

    # OCR翻译阶段
    TRANSLATING = 'translating'
    TRANSLATED = 'translated'

    # 实体识别阶段
    ENTITY_RECOGNIZING = 'entity_recognizing'
    ENTITY_PENDING_CONFIRM = 'entity_pending_confirm'
    ENTITY_CONFIRMED = 'entity_confirmed'

    # LLM优化阶段
    LLM_TRANSLATING = 'llm_translating'
    LLM_TRANSLATED = 'llm_translated'

    # 完成阶段
    CONFIRMED = 'confirmed'

    # 错误状态
    FAILED = 'failed'


class AtomicAction(str, Enum):
    """原子操作枚举"""
    TRANSLATE_BAIDU = 'translate_baidu'
    ENTITY_RECOGNIZE = 'entity_recognize'
    ENTITY_CONFIRM = 'entity_confirm'
    ENTITY_SKIP = 'entity_skip'
    LLM_OPTIMIZE = 'llm_optimize'
    LLM_RETRY = 'llm_retry'
    REVIEW = 'review'
    SKIP_TO_REVIEW = 'skip_to_review'
    RETRANSLATE = 'retranslate'


class AtomicStateMachine:
    """
    原子化状态机 - 管理状态转换和可用操作

    设计目标：
    - 保证调用灵活度，每个操作可独立调用
    - 但不改变默认行为，start_translation 仍可触发完整流程
    """

    # 状态转换规则：当前状态 -> {操作: 目标状态}
    TRANSITIONS: Dict[str, Dict[str, str]] = {
        ProcessingStep.UPLOADED.value: {
            AtomicAction.TRANSLATE_BAIDU.value: ProcessingStep.TRANSLATED.value,
        },
        ProcessingStep.SPLIT_COMPLETED.value: {
            AtomicAction.TRANSLATE_BAIDU.value: ProcessingStep.TRANSLATED.value,
        },
        ProcessingStep.TRANSLATED.value: {
            AtomicAction.ENTITY_RECOGNIZE.value: ProcessingStep.ENTITY_RECOGNIZING.value,
            AtomicAction.LLM_OPTIMIZE.value: ProcessingStep.LLM_TRANSLATING.value,
            AtomicAction.SKIP_TO_REVIEW.value: ProcessingStep.CONFIRMED.value,
        },
        ProcessingStep.ENTITY_RECOGNIZING.value: {
            # 识别完成后自动转换到 pending_confirm（由识别服务处理）
        },
        ProcessingStep.ENTITY_PENDING_CONFIRM.value: {
            AtomicAction.ENTITY_CONFIRM.value: ProcessingStep.ENTITY_CONFIRMED.value,
            AtomicAction.ENTITY_SKIP.value: ProcessingStep.TRANSLATED.value,
        },
        ProcessingStep.ENTITY_CONFIRMED.value: {
            AtomicAction.LLM_OPTIMIZE.value: ProcessingStep.LLM_TRANSLATING.value,
            AtomicAction.SKIP_TO_REVIEW.value: ProcessingStep.CONFIRMED.value,
        },
        ProcessingStep.LLM_TRANSLATING.value: {
            # LLM完成后自动转换到 llm_translated（由LLM服务处理）
        },
        ProcessingStep.LLM_TRANSLATED.value: {
            AtomicAction.REVIEW.value: ProcessingStep.CONFIRMED.value,
            AtomicAction.LLM_RETRY.value: ProcessingStep.LLM_TRANSLATING.value,
        },
        ProcessingStep.CONFIRMED.value: {
            AtomicAction.RETRANSLATE.value: ProcessingStep.UPLOADED.value,
        },
        ProcessingStep.FAILED.value: {
            AtomicAction.RETRANSLATE.value: ProcessingStep.UPLOADED.value,
            AtomicAction.TRANSLATE_BAIDU.value: ProcessingStep.TRANSLATED.value,
        },
    }

    # 允许从任意状态执行的操作（用于重新翻译等场景）
    GLOBAL_ACTIONS: Set[str] = {
        AtomicAction.RETRANSLATE.value,
        AtomicAction.TRANSLATE_BAIDU.value,  # 允许重新翻译
    }

    def can_do(self, current_step: str, action: str) -> bool:
        """
        检查当前状态是否允许执行某操作

        Args:
            current_step: 当前处理步骤
            action: 要执行的操作

        Returns:
            是否允许执行
        """
        # 全局操作总是允许
        if action in self.GLOBAL_ACTIONS:
            return True

        # 检查状态转换规则
        transitions = self.TRANSITIONS.get(current_step, {})
        return action in transitions

    def do_transition(self, current_step: str, action: str) -> Optional[str]:
        """
        执行状态转换，返回新状态

        Args:
            current_step: 当前处理步骤
            action: 要执行的操作

        Returns:
            新状态，如果转换不合法则返回 None
        """
        if not self.can_do(current_step, action):
            logger.warning(f"状态转换不合法: {current_step} -> {action}")
            return None

        # 全局操作的目标状态
        if action == AtomicAction.RETRANSLATE.value:
            return ProcessingStep.UPLOADED.value
        if action == AtomicAction.TRANSLATE_BAIDU.value:
            return ProcessingStep.TRANSLATED.value

        # 正常状态转换
        transitions = self.TRANSITIONS.get(current_step, {})
        return transitions.get(action)

    def get_available_actions(self, current_step: str) -> List[str]:
        """
        获取当前状态可用的操作列表

        Args:
            current_step: 当前处理步骤

        Returns:
            可用操作列表
        """
        transitions = self.TRANSITIONS.get(current_step, {})
        actions = list(transitions.keys())

        # 添加全局操作（除了当前状态已有的）
        for action in self.GLOBAL_ACTIONS:
            if action not in actions:
                actions.append(action)

        return actions

    def get_next_step(self, current_step: str, action: str) -> Optional[str]:
        """
        获取执行操作后的下一个状态（不实际执行转换）

        Args:
            current_step: 当前处理步骤
            action: 要执行的操作

        Returns:
            下一个状态
        """
        return self.do_transition(current_step, action)

    @staticmethod
    def is_processing_state(step: str) -> bool:
        """检查是否是处理中状态（不应该允许新操作）"""
        processing_states = {
            ProcessingStep.TRANSLATING.value,
            ProcessingStep.ENTITY_RECOGNIZING.value,
            ProcessingStep.LLM_TRANSLATING.value,
            ProcessingStep.SPLITTING.value,
        }
        return step in processing_states

    @staticmethod
    def is_waiting_user_input(step: str) -> bool:
        """检查是否在等待用户输入（卡关状态）"""
        return step == ProcessingStep.ENTITY_PENDING_CONFIRM.value

    @staticmethod
    def is_completed(step: str) -> bool:
        """检查是否已完成"""
        completed_states = {
            ProcessingStep.LLM_TRANSLATED.value,
            ProcessingStep.CONFIRMED.value,
        }
        return step in completed_states


# 单例实例
state_machine = AtomicStateMachine()


def validate_transition(current_step: str, action: str) -> tuple:
    """
    验证状态转换的便捷函数

    Returns:
        (is_valid, next_step, error_message)
    """
    if state_machine.is_processing_state(current_step):
        return False, None, f"当前状态 {current_step} 正在处理中，请等待完成"

    if not state_machine.can_do(current_step, action):
        available = state_machine.get_available_actions(current_step)
        return False, None, f"当前状态 {current_step} 不支持操作 {action}，可用操作: {available}"

    next_step = state_machine.do_transition(current_step, action)
    return True, next_step, None

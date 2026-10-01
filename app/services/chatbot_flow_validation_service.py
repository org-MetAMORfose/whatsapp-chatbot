"""Structural validation for published and draft chatbot graphs."""

from collections import deque
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agent.chat_flow import ActionTransitionConfig, ChatFlow, Node, Transition
from app.domain.enum.chatbot_flow import NodeType

BUTTON_LABEL_MAX_LENGTH = 20


class FlowValidationError(BaseModel):
    code: str
    message: str
    node_id: int | None = None
    node_key: str | None = None
    transition_id: int | None = None
    action_id: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class FlowValidationResult(BaseModel):
    valid: bool
    errors: list[FlowValidationError]


class ChatFlowValidator:
    def validate(
        self,
        flow: ChatFlow,
        *,
        deleted_required_nodes: list[tuple[int, str]] | None = None,
    ) -> FlowValidationResult:
        errors: list[FlowValidationError] = []
        adjacency: dict[str, set[str]] = {key: set() for key in flow.nodes}

        for node in flow.nodes.values():
            if node.type == NodeType.END and node.transitions:
                errors.append(
                    self._error(
                        "END_HAS_TRANSITIONS",
                        "Um nó END não pode possuir transições.",
                        node,
                    )
                )
            for transition in node.transitions:
                if transition.button_label is not None and len(transition.button_label) > BUTTON_LABEL_MAX_LENGTH:
                    errors.append(
                        self._error(
                            "BUTTON_LABEL_TOO_LONG",
                            f"O botão deve ter no máximo {BUTTON_LABEL_MAX_LENGTH} caracteres.",
                            node,
                            transition_id=transition.id,
                            details={
                                "max_length": BUTTON_LABEL_MAX_LENGTH,
                                "actual_length": len(transition.button_label),
                            },
                        )
                    )
                if transition.target in flow.nodes:
                    adjacency[node.key].add(transition.target)
                else:
                    errors.append(
                        self._error(
                            "TRANSITION_TARGET_NOT_FOUND",
                            "O destino da transição não existe.",
                            node,
                            transition_id=transition.id,
                            details={"target_node_key": transition.target},
                        )
                    )
                for action in transition.actions:
                    if action.config is None:
                        continue
                    try:
                        config = ActionTransitionConfig.model_validate(action.config)
                    except ValidationError as exc:
                        errors.append(
                            self._error(
                                "INVALID_ACTION_CONFIG",
                                "O config da action não possui formato ou operador válido.",
                                node,
                                transition_id=transition.id,
                                action_id=action.id,
                                details={"validation_errors": exc.errors(include_url=False)},
                            )
                        )
                        continue
                    if config.target_node_key not in flow.nodes:
                        errors.append(
                            self._error(
                                "INVALID_ACTION_CONFIG_TARGET",
                                "O destino declarado pelo config da action não existe.",
                                node,
                                transition_id=transition.id,
                                action_id=action.id,
                                details={"target_node_key": config.target_node_key},
                            )
                        )
                        continue
                    adjacency[node.key].add(config.target_node_key)

        can_reach_end = self._nodes_reaching_end(flow, adjacency)
        for node in flow.nodes.values():
            if node.key not in can_reach_end:
                errors.append(
                    self._error(
                        "NODE_CANNOT_REACH_END",
                        "O nó não possui caminho até um END.",
                        node,
                    )
                )

        reachable_from_start = self._reachable_from_starts(flow, adjacency)
        for node in flow.nodes.values():
            if node.type != NodeType.START and node.key not in reachable_from_start:
                errors.append(
                    self._error(
                        "NODE_NOT_REACHABLE_FROM_START",
                        "O nó não pode ser alcançado a partir de nenhum START.",
                        node,
                    )
                )

        errors.extend(self._validate_action_dependencies(flow, adjacency))
        for node_id, node_key in deleted_required_nodes or []:
            errors.append(
                FlowValidationError(
                    code="REQUIRED_ACTION_NODE_DELETE",
                    message="Um nó com action obrigatória não pode ser apagado.",
                    node_id=node_id,
                    node_key=node_key,
                )
            )
        return FlowValidationResult(valid=not errors, errors=errors)

    @staticmethod
    def _nodes_reaching_end(
        flow: ChatFlow,
        adjacency: dict[str, set[str]],
    ) -> set[str]:
        reverse: dict[str, set[str]] = {key: set() for key in flow.nodes}
        for source, targets in adjacency.items():
            for target in targets:
                reverse[target].add(source)
        reachable = {node.key for node in flow.nodes.values() if node.type == NodeType.END}
        queue = deque(reachable)
        while queue:
            target = queue.popleft()
            for source in reverse[target]:
                if source not in reachable:
                    reachable.add(source)
                    queue.append(source)
        return reachable

    @staticmethod
    def _reachable_from_starts(
        flow: ChatFlow,
        adjacency: dict[str, set[str]],
    ) -> set[str]:
        reachable = {node.key for node in flow.nodes.values() if node.type == NodeType.START}
        queue = deque(reachable)
        while queue:
            source = queue.popleft()
            for target in adjacency[source]:
                if target not in reachable:
                    reachable.add(target)
                    queue.append(target)
        return reachable

    def _validate_action_dependencies(
        self,
        flow: ChatFlow,
        adjacency: dict[str, set[str]],
    ) -> list[FlowValidationError]:
        errors: list[FlowValidationError] = []
        actions: dict[int, tuple[Node, Transition, int]] = {}
        dependencies: dict[int, list[int]] = {}
        for node in flow.nodes.values():
            for transition in node.transitions:
                for index, action in enumerate(transition.actions):
                    if action.id is None:
                        continue
                    actions[action.id] = (node, transition, index)
                    dependencies[action.id] = list(action.depends_on_ids)

        cycle = self._dependency_cycle(dependencies)
        if cycle:
            action_id = cycle[0]
            location = actions.get(action_id)
            cycle_node = location[0] if location is not None else None
            cycle_transition = location[1] if location is not None else None
            errors.append(
                FlowValidationError(
                    code="CIRCULAR_ACTION_DEPENDENCY",
                    message="As dependências entre actions formam um ciclo.",
                    node_id=cycle_node.id if cycle_node else None,
                    node_key=cycle_node.key if cycle_node else None,
                    transition_id=cycle_transition.id if cycle_transition else None,
                    action_id=action_id,
                    details={"action_ids": cycle},
                )
            )

        for action_id, dependency_ids in dependencies.items():
            location = actions.get(action_id)
            if location is None:
                continue
            node, transition, _ = location
            for dependency_id in dependency_ids:
                if dependency_id not in actions:
                    errors.append(
                        self._error(
                            "ACTION_DEPENDENCY_NOT_FOUND",
                            "A dependência da action não existe no grafo.",
                            node,
                            transition_id=transition.id,
                            action_id=action_id,
                            details={"depends_on_id": dependency_id},
                        )
                    )
                    continue
                if not self._dependency_precedes(
                    flow,
                    adjacency,
                    dependency_id=dependency_id,
                    action_id=action_id,
                ):
                    errors.append(
                        self._error(
                            "ACTION_DEPENDENCY_NOT_BEFORE",
                            "A action dependente pode executar antes de sua dependência.",
                            node,
                            transition_id=transition.id,
                            action_id=action_id,
                            details={"depends_on_id": dependency_id},
                        )
                    )
        return errors

    @staticmethod
    def _dependency_cycle(dependencies: dict[int, list[int]]) -> list[int] | None:
        visiting: list[int] = []
        visited: set[int] = set()

        def visit(action_id: int) -> list[int] | None:
            if action_id in visiting:
                start = visiting.index(action_id)
                return [*visiting[start:], action_id]
            if action_id in visited:
                return None
            visiting.append(action_id)
            for dependency_id in dependencies.get(action_id, []):
                cycle = visit(dependency_id)
                if cycle:
                    return cycle
            visiting.pop()
            visited.add(action_id)
            return None

        for action_id in dependencies:
            cycle = visit(action_id)
            if cycle:
                return cycle
        return None

    @staticmethod
    def _dependency_precedes(
        flow: ChatFlow,
        adjacency: dict[str, set[str]],
        *,
        dependency_id: int,
        action_id: int,
    ) -> bool:
        starts = [node.key for node in flow.nodes.values() if node.type == NodeType.START]
        queue = deque((start, False) for start in starts)
        visited: set[tuple[str, bool]] = set()
        while queue:
            node_key, dependency_seen = queue.popleft()
            if (node_key, dependency_seen) in visited:
                continue
            visited.add((node_key, dependency_seen))
            node = flow.nodes[node_key]
            for transition in node.transitions:
                seen = dependency_seen
                for action in transition.actions:
                    if action.id == action_id and not seen:
                        return False
                    if action.id == dependency_id:
                        seen = True
                targets = {transition.target}
                for transition_action in transition.actions:
                    if transition_action.config is None:
                        continue
                    try:
                        config = ActionTransitionConfig.model_validate(transition_action.config)
                    except ValidationError:
                        continue
                    targets.add(config.target_node_key)
                for target in targets & adjacency.keys():
                    queue.append((target, seen))
        return True

    @staticmethod
    def _error(
        code: str,
        message: str,
        node: Node,
        *,
        transition_id: int | None = None,
        action_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> FlowValidationError:
        return FlowValidationError(
            code=code,
            message=message,
            node_id=node.id,
            node_key=node.key,
            transition_id=transition_id,
            action_id=action_id,
            details=details or {},
        )

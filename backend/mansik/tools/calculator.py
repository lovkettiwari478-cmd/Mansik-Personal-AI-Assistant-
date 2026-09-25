"""Safe arithmetic calculator tool.

Evaluates expressions via a whitelisted AST walk — never eval(), no
attribute access, no function calls except an explicit math whitelist.
"""

from __future__ import annotations

import ast
import math
from typing import Any

from ..config import RISK_READ
from ..errors import ValidationAppError
from .base import Tool, ToolContext, ToolParams
from pydantic import Field


class CalculateParams(ToolParams):
    expression: str = Field(..., min_length=1, max_length=500, description="Arithmetic expression, e.g. (2+3)*7^2 / sqrt(16)")


_MAX_NUMBER = 1e100


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValidationAppError("Only numeric constants are allowed.")
        return float(node.value)
    if isinstance(node, ast.BinOp):
        op = node.op
        left, right = _safe_eval(node.left), _safe_eval(node.right)
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            if right == 0:
                raise ValidationAppError("Division by zero.")
            return left / right
        if isinstance(op, ast.Pow):
            if abs(right) > 1000 or abs(left) > 1e6 and abs(right) > 32:
                raise ValidationAppError("Exponent too large.")
            return left ** right
        if isinstance(op, ast.Mod):
            if right == 0:
                raise ValidationAppError("Modulo by zero.")
            return left % right
        if isinstance(op, ast.FloorDiv):
            if right == 0:
                raise ValidationAppError("Division by zero.")
            return left // right
        raise ValidationAppError("Unsupported operator.")
    if isinstance(node, ast.UnaryOp):
        val = _safe_eval(node.operand)
        if isinstance(node.op, ast.USub):
            return -val
        if isinstance(node.op, ast.UAdd):
            return val
        raise ValidationAppError("Unsupported unary operator.")
    if isinstance(node, ast.Call):
        # only whitelisted pure math functions, constant arity
        func = node.func
        if not isinstance(func, ast.Name) or func.id not in _FUNCTIONS:
            raise ValidationAppError("Function not allowed.")
        if node.keywords:
            raise ValidationAppError("Keyword arguments not allowed.")
        args = [_safe_eval(a) for a in node.args]
        if len(args) not in _FUNCTIONS[func.id][1]:
            raise ValidationAppError("Wrong number of arguments.")
        return _FUNCTIONS[func.id][0](*args)
    raise ValidationAppError(f"Unsupported syntax: {type(node).__name__}.")


_FUNCTIONS: dict[str, tuple[Any, tuple[int, ...]]] = {
    "sqrt": (math.sqrt, (1,)),
    "abs": (abs, (1,)),
    "sin": (math.sin, (1,)),
    "cos": (math.cos, (1,)),
    "tan": (math.tan, (1,)),
    "log": (math.log, (1, 2)),
    "log10": (math.log10, (1,)),
    "exp": (math.exp, (1,)),
    "floor": (math.floor, (1,)),
    "ceil": (math.ceil, (1,)),
    "round": (round, (1, 2)),
    "min": (min, (1, 2, 3, 4, 5)),
    "max": (max, (1, 2, 3, 4, 5)),
}


def safe_calculate(expression: str) -> float:
    # normalize common aliases
    expression = expression.replace("^", "**").replace("×", "*").replace("÷", "/")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        raise ValidationAppError("Could not parse the expression.")
    result = _safe_eval(tree)
    if not math.isfinite(result):
        raise ValidationAppError("Result is not a finite number.")
    if abs(result) > _MAX_NUMBER:
        raise ValidationAppError("Result out of range.")
    return result


class CalculatorTool(Tool):
    id = "math.calculate"
    name = "Calculator"
    description = "Evaluate arithmetic expressions: + - * / % // ** and functions sqrt, sin, cos, tan, log, exp, floor, ceil, round, min, max, abs."
    category = "utility"
    risk = RISK_READ
    timeout_seconds = 5.0

    params_model = CalculateParams

    async def run(self, ctx: ToolContext, params: CalculateParams) -> dict:
        result = safe_calculate(params.expression)
        pretty = f"{result:g}"
        return {"expression": params.expression, "result": result, "pretty": pretty}

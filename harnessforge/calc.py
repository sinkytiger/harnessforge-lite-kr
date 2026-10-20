"""A small, safe arithmetic evaluator shared by the compute tool and the gold-answer generator."""

from __future__ import annotations

import ast
import re

_ALLOWED_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                   ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}
_NAME = re.compile(r"\b([A-Z][0-9]+)\b")


class CalcError(ValueError):
    pass


def names_in(expr: str) -> list[str]:
    return _NAME.findall(expr or "")


def evaluate(expr: str, env: dict[str, float] | None = None) -> float:
    """Evaluate +, -, *, / over numbers and named values such as E3 or F0.

    Thousands separators inside numbers are tolerated ("1,234 / 10" is read as 1234 / 10), since
    models often copy figures exactly as printed.
    """
    env = env or {}
    cleaned = re.sub(r"(?<=\d),(?=\d{3}\b)", "", (expr or "").strip())
    cleaned = cleaned.replace("×", "*").replace("÷", "/").replace("△", "-")
    if not cleaned:
        raise CalcError("empty expression")
    if len(cleaned) > 300:
        raise CalcError("expression too long")
    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError as exc:
        raise CalcError(f"cannot parse expression: {expr!r}") from exc

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise CalcError(f"unknown name {node.id}")
            return float(env[node.id])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            # roots and small powers only (e.g. CAGR uses ** 0.5); the exponent may not use names
            if any(isinstance(n, ast.Name) for n in ast.walk(node.right)):
                raise CalcError("the exponent must be a constant")
            base, exp = ev(node.left), ev(node.right)
            if abs(exp) > 4:
                raise CalcError("exponent too large")
            if base < 0 and not float(exp).is_integer():
                raise CalcError("fractional power of a negative number")
            return base ** exp
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Div) and b == 0:
                raise CalcError("division by zero")
            return _ALLOWED_BINOPS[type(node.op)](a, b)
        raise CalcError(f"unsupported syntax in {expr!r}")

    return ev(tree)

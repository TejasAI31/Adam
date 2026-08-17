"""Comprehensive math and advanced calculation tools for Adam."""

import math
import cmath
import statistics
import numpy as np


def evaluate_expression(expression: str) -> str:
    """Safely evaluate a complex mathematical expression using Python's math and numpy libraries."""
    allowed_names = {
        k: v for k, v in math.__dict__.items() if not k.startswith("__")
    }
    allowed_names.update({
        k: v for k, v in cmath.__dict__.items() if not k.startswith("__")
    })
    allowed_names.update({
        k: v for k, v in statistics.__dict__.items() if not k.startswith("__")
    })
    allowed_names.update({
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "pow": pow,
        "np": np,
    })
    try:
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return str(result)
    except Exception as e:
        return f"Error evaluating mathematical expression: {e}"


def solve_quadratic(a: float, b: float, c: float) -> str:
    """Solve a quadratic equation of the form ax^2 + bx + c = 0, returning real or complex roots."""
    try:
        discriminant = (b ** 2) - (4 * a * c)
        root1 = (-b + cmath.sqrt(discriminant)) / (2 * a)
        root2 = (-b - cmath.sqrt(discriminant)) / (2 * a)
        if root1 == root2:
            return f"Single root: {root1}"
        return f"Roots: {root1}, {root2}"
    except Exception as e:
        return f"Error solving quadratic equation: {e}"


def calculate_statistics(numbers: list) -> str:
    """Calculate descriptive statistics (mean, median, mode, variance, standard deviation) for a list of numbers."""
    try:
        if not numbers:
            return "Error: Empty list provided."
        mean_val = statistics.mean(numbers)
        median_val = statistics.median(numbers)
        try:
            mode_val = statistics.mode(numbers)
        except statistics.StatisticsError:
            mode_val = "No unique mode"
        stdev_val = statistics.stdev(numbers) if len(numbers) > 1 else 0.0
        variance_val = statistics.variance(numbers) if len(numbers) > 1 else 0.0
        
        return (
            f"Mean: {mean_val}, Median: {median_val}, Mode: {mode_val}, "
            f"Standard Deviation: {stdev_val}, Variance: {variance_val}"
        )
    except Exception as e:
        return f"Error calculating statistics: {e}"

# OpenAI-compatible tool definitions schema for llama-server
MATH_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "evaluate_expression",
            "description": "Evaluate any advanced math expression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The mathematical expression string to compute.",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solve_quadratic",
            "description": "Solve quadratic equations of form ax^2 + bx + c = 0.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "Coefficient a"},
                    "b": {"type": "number", "description": "Coefficient b"},
                    "c": {"type": "number", "description": "Coefficient c"},
                },
                "required": ["a", "b", "c"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_statistics",
            "description": "Compute mean, median, mode, variance, and standard deviation for a sequence of numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "numbers": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "List of numeric values.",
                    }
                },
                "required": ["numbers"],
            },
        },
    },
]

# Registry mapping names to functions
MATH_TOOLS_MAP = {
    "evaluate_expression": evaluate_expression,
    "solve_quadratic": solve_quadratic,
    "calculate_statistics": calculate_statistics,
}
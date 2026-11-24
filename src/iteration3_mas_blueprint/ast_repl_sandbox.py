"""Iteration 3 Blueprint — AST-Secured Python REPL Sandbox & V&V Evaluator.

ARCHITECTURAL REFERENCE IMPLEMENTATION (Sprint-Ready Blueprint):
Implements the bottom and right side of the Contract-Driven Agentic V-Model
from `docs/whitepaper/QA_Agent_SOP.pdf`:
  1. AST Security Sandbox (`SafeMathASTVisitor`): Explicitly forbids Python `eval()`,
     restricting expression evaluation strictly to an allowlist of AST math nodes.
  2. Hardcoded Equation Registry: Equations are never supplied by an LLM.
  3. ASME V&V 20 Separation: Independently executes Numerical Verification (IEEE-754
     tolerance 1e-4) and Physics Validation (e.g., Hazen-Williams C-factor table,
     temperature 4-14 C, velocity <= 7.6 m/s per NFPA 750).
  4. Zero-Inference Rule: Halts and emits `[FATAL ERROR]` with `calculated_result=None`
     on missing variables, ZeroDivisionError, or AST security violations.
  5. Track A Statutory Verbatim Checker & Track B Semantic Threshold Evaluator.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from typing import Any, Callable

from src.iteration3_mas_blueprint.qa_contracts import (
    AdjudicationFlag,
    ContextualContract,
    MathematicalContract,
    OperationalTrack,
    SoftwareIntegrityLevel,
    StatutoryContract,
    ValidationReport,
)

IEEE_754_TOLERANCE = 1e-4

# Verified Hazen-Williams C-factor material reference table (SOP Section 2)
VERIFIED_C_FACTORS: dict[str, float] = {
    "plastic": 150.0,
    "cpvc": 150.0,
    "hdpe": 150.0,
    "stainless_steel": 150.0,
    "copper": 150.0,
    "galvanized_steel": 120.0,
    "black_steel_wet": 120.0,
    "black_steel_dry": 100.0,
    "cast_iron": 100.0,
}

# Hardcoded Fire Safety Engineering Equations (Never LLM-generated)
EQUATION_REGISTRY: dict[str, tuple[str, set[str]]] = {
    # SOP Eq.: p = 6.05e5 * Q^1.85 * C^(-1.85) * d^(-4.87)  [bar/m; Q in L/min, d in mm]
    "hazen_williams": (
        "6.05e5 * (Q ** 1.85) * (C ** -1.85) * (d ** -4.87)",
        {"Q", "C", "d"},
    ),
    # Darcy-Weisbach pressure drop in bar: f * (L / D) * (rho * v^2 / 2) / 1e5
    "darcy_weisbach": (
        "(f * (L / D) * (rho * (v ** 2) / 2.0)) / 1e5",
        {"f", "L", "D", "rho", "v"},
    ),
    # NFPA 557 Fire Load Energy Density (MJ/m^2): (mass_kg * calorific_mj_per_kg) / floor_area_m2
    "nfpa_557_fire_load": (
        "(mass_kg * calorific_mj_per_kg) / floor_area_m2",
        {"mass_kg", "calorific_mj_per_kg", "floor_area_m2"},
    ),
    # Bernoulli total hydraulic head (m): P/(rho*g) + v^2/(2*g) + z
    "bernoulli_head": (
        "(P / (rho * g)) + ((v ** 2) / (2.0 * g)) + z",
        {"P", "rho", "g", "v", "z"},
    ),
    # NBC 2016 Part 4 Cl. 3.4.6.4: 110% secondary containment dyke volume
    "dyke_containment_110": (
        "1.10 * tank_volume_liters",
        {"tank_volume_liters"},
    ),
}

SAFE_BIN_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}

SAFE_UNARY_OPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

SAFE_FUNCTIONS: dict[str, Callable[..., float]] = {
    "sqrt": math.sqrt,
    "pow": math.pow,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
}


class ASTSecurityViolation(SecurityError if hasattr(__builtins__, "SecurityError") else Exception):
    """Raised immediately when an unauthorized AST node or injection attempt is detected."""


class SafeMathASTVisitor(ast.NodeVisitor):
    """Walks an AST and enforces a strict mathematical allowlist before evaluation."""

    ALLOWED_NODES = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.Call,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.UAdd,
        ast.USub,
    )

    def __init__(self, allowed_names: set[str]) -> None:
        self.allowed_names = allowed_names | set(SAFE_FUNCTIONS.keys())

    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, self.ALLOWED_NODES):
            raise ASTSecurityViolation(
                f"Unauthorized AST node detected: {type(node).__name__}"
            )
        super().generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__") or node.id not in self.allowed_names:
            raise ASTSecurityViolation(f"Unauthorized identifier in expression: '{node.id}'")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
            raise ASTSecurityViolation(f"Non-numeric constant disallowed: {node.value!r}")

    def visit_Call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_FUNCTIONS:
            raise ASTSecurityViolation("Only allowlisted mathematical functions may be called.")
        if node.keywords:
            raise ASTSecurityViolation("Keyword arguments are disallowed in math sandbox calls.")
        self.generic_visit(node)


def _eval_ast_node(node: ast.AST, variables: dict[str, float]) -> float:
    """Recursively evaluates a pre-validated AST without ever invoking Python eval()."""
    if isinstance(node, ast.Expression):
        return _eval_ast_node(node.body, variables)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return float(variables[node.id])
    if isinstance(node, ast.UnaryOp):
        op_fn = SAFE_UNARY_OPS[type(node.op)]
        return float(op_fn(_eval_ast_node(node.operand, variables)))
    if isinstance(node, ast.BinOp):
        op_fn = SAFE_BIN_OPS[type(node.op)]
        left = _eval_ast_node(node.left, variables)
        right = _eval_ast_node(node.right, variables)
        return float(op_fn(left, right))
    if isinstance(node, ast.Call):
        func_name = node.func.id  # validated by SafeMathASTVisitor
        args = [_eval_ast_node(arg, variables) for arg in node.args]
        return float(SAFE_FUNCTIONS[func_name](*args))
    raise ASTSecurityViolation(f"Unsupported AST node during evaluation: {type(node).__name__}")


def safe_evaluate_expression(expression: str, variables: dict[str, float]) -> float:
    """Parses, security-audits, and deterministically evaluates a math expression."""
    tree = ast.parse(expression, mode="eval")
    SafeMathASTVisitor(allowed_names=set(variables.keys())).visit(tree)
    return _eval_ast_node(tree, variables)


def _validate_physics_context(contract: MathematicalContract) -> tuple[bool, list[str]]:
    """ASME V&V 20 Validation: Checks whether the selected equation matches physical COU."""
    reasons: list[str] = []
    cou = contract.context_of_use

    if contract.equation_type == "hazen_williams":
        if cou.is_water_mist_system:
            reasons.append(
                "Hazen-Williams is invalid for high-pressure water mist systems; NFPA 750 mandates Darcy-Weisbach."
            )
        if cou.flow_velocity_m_s is not None and cou.flow_velocity_m_s > 7.6:
            reasons.append(
                f"Fluid velocity ({cou.flow_velocity_m_s} m/s) exceeds 7.6 m/s Hazen-Williams boundary; use Darcy-Weisbach."
            )
        if cou.fluid_temp_c is not None and not (4.0 <= cou.fluid_temp_c <= 14.0):
            reasons.append(
                f"Water temperature ({cou.fluid_temp_c} C) lies outside the 4-14 C Hazen-Williams viscosity range; verify via Darcy-Weisbach."
            )
        if cou.pipe_material:
            mat_key = cou.pipe_material.strip().lower().replace(" ", "_")
            expected_c = VERIFIED_C_FACTORS.get(mat_key)
            claimed_c = contract.input_parameters.get("C")
            if expected_c is not None and claimed_c is not None and abs(claimed_c - expected_c) > 1e-6:
                reasons.append(
                    f"C-factor mismatch for '{cou.pipe_material}': claimed C={claimed_c}, verified table C={expected_c}."
                )

    return len(reasons) == 0, reasons


def evaluate_mathematical_contract(contract: MathematicalContract) -> ValidationReport:
    """Runs Track A Verification (AST REPL) and ASME V&V 20 Physics Validation."""
    expr, required_vars = EQUATION_REGISTRY[contract.equation_type]
    missing_vars = sorted(required_vars - set(contract.input_parameters.keys()))

    # Zero-Inference Rule: halt immediately on missing variables
    if missing_vars:
        return ValidationReport(
            claim_id=contract.claim_id,
            track=OperationalTrack.TRACK_A,
            sil=contract.sil,
            verification_passed=False,
            validation_passed=False,
            flag=AdjudicationFlag.FATAL_ERROR,
            calculated_result=None,
            claimed_result=contract.claimed_result,
            diagnostic_trace=(
                f"Zero-Inference Halt: Missing required input parameters {missing_vars} "
                f"for '{contract.equation_type}'."
            ),
            requires_human_adjudication=True,
        )

    # Step 1: Deterministic Numerical Verification via AST Sandbox
    try:
        calculated = safe_evaluate_expression(expr, contract.input_parameters)
    except (ASTSecurityViolation, ZeroDivisionError, ValueError, OverflowError) as exc:
        return ValidationReport(
            claim_id=contract.claim_id,
            track=OperationalTrack.TRACK_A,
            sil=contract.sil,
            verification_passed=False,
            validation_passed=False,
            flag=AdjudicationFlag.FATAL_ERROR,
            calculated_result=None,
            claimed_result=contract.claimed_result,
            diagnostic_trace=f"AST Sandbox Execution Halted ({type(exc).__name__}): {exc}",
            requires_human_adjudication=True,
        )

    deviation = abs(calculated - contract.claimed_result)
    verification_passed = deviation <= IEEE_754_TOLERANCE

    # Step 2: ASME V&V 20 Physics Validation
    validation_passed, physics_issues = _validate_physics_context(contract)

    if not verification_passed:
        return ValidationReport(
            claim_id=contract.claim_id,
            track=OperationalTrack.TRACK_A,
            sil=contract.sil,
            verification_passed=False,
            validation_passed=validation_passed,
            flag=AdjudicationFlag.FATAL_ERROR,
            calculated_result=round(calculated, 6),
            claimed_result=contract.claimed_result,
            absolute_deviation=round(deviation, 6),
            diagnostic_trace=(
                f"Deterministic Math Failure: Claimed {contract.claimed_result}, "
                f"REPL calculated {calculated:.6f} (deviation {deviation:.6f} > {IEEE_754_TOLERANCE})."
            ),
            requires_human_adjudication=True,
        )

    if not validation_passed:
        return ValidationReport(
            claim_id=contract.claim_id,
            track=OperationalTrack.TRACK_A,
            sil=contract.sil,
            verification_passed=True,
            validation_passed=False,
            flag=AdjudicationFlag.CONTEXTUAL_FAILURE,
            calculated_result=round(calculated, 6),
            claimed_result=contract.claimed_result,
            absolute_deviation=round(deviation, 6),
            diagnostic_trace="ASME V&V 20 Physics Validation Failed: " + " | ".join(physics_issues),
            requires_human_adjudication=True,
        )

    return ValidationReport(
        claim_id=contract.claim_id,
        track=OperationalTrack.TRACK_A,
        sil=contract.sil,
        verification_passed=True,
        validation_passed=True,
        flag=AdjudicationFlag.PASSED,
        calculated_result=round(calculated, 6),
        claimed_result=contract.claimed_result,
        absolute_deviation=round(deviation, 6),
        diagnostic_trace="Verified deterministically within IEEE-754 tolerance and valid physical COU.",
        requires_human_adjudication=False,
    )


def _normalize_for_verbatim_check(text: str) -> str:
    """Normalizes minor whitespace and typographic punctuation without altering tokens."""
    cleaned = re.sub(r"[\u2018\u2019]", "'", text)
    cleaned = re.sub(r"[\u201c\u201d]", '"', cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def evaluate_statutory_contract(
    contract: StatutoryContract,
    authoritative_clause_text: str | None,
) -> ValidationReport:
    """Enforces Track A 100% verbatim statutory quote matching (Zero-Inference Rule)."""
    if not authoritative_clause_text:
        return ValidationReport(
            claim_id=contract.claim_id,
            track=OperationalTrack.TRACK_A,
            sil=contract.sil,
            verification_passed=False,
            validation_passed=False,
            flag=AdjudicationFlag.FATAL_ERROR,
            diagnostic_trace=(
                f"Statutory Hallucination (Zero-Inference Halt): Clause '{contract.clause_number}' "
                f"of '{contract.referenced_standard}' was not found in the authoritative JSON codebase."
            ),
            requires_human_adjudication=True,
        )

    norm_quoted = _normalize_for_verbatim_check(contract.quoted_text)
    norm_truth = _normalize_for_verbatim_check(authoritative_clause_text)

    if norm_quoted and norm_quoted in norm_truth:
        return ValidationReport(
            claim_id=contract.claim_id,
            track=OperationalTrack.TRACK_A,
            sil=contract.sil,
            verification_passed=True,
            validation_passed=True,
            flag=AdjudicationFlag.PASSED,
            diagnostic_trace=(
                f"Verbatim match confirmed against {contract.referenced_standard} "
                f"Clause {contract.clause_number}."
            ),
            requires_human_adjudication=False,
        )

    return ValidationReport(
        claim_id=contract.claim_id,
        track=OperationalTrack.TRACK_A,
        sil=contract.sil,
        verification_passed=False,
        validation_passed=False,
        flag=AdjudicationFlag.FATAL_ERROR,
        diagnostic_trace=(
            f"Statutory Deviation Detected: Quoted text deviates from authoritative "
            f"{contract.referenced_standard} Clause {contract.clause_number}."
        ),
        requires_human_adjudication=True,
    )


def evaluate_contextual_contract(contract: ContextualContract) -> ValidationReport:
    """Evaluates Track B qualitative technical statements against SOP similarity thresholds."""
    score = contract.cosine_similarity
    if score is None:
        return ValidationReport(
            claim_id=contract.claim_id,
            track=OperationalTrack.TRACK_B,
            sil=contract.sil,
            verification_passed=False,
            validation_passed=False,
            flag=AdjudicationFlag.FATAL_ERROR,
            diagnostic_trace="Missing semantic similarity score against verified engineering baseline.",
            requires_human_adjudication=True,
        )

    if score < 0.75:
        return ValidationReport(
            claim_id=contract.claim_id,
            track=OperationalTrack.TRACK_B,
            sil=contract.sil,
            verification_passed=False,
            validation_passed=False,
            flag=AdjudicationFlag.FATAL_ERROR,
            diagnostic_trace=(
                f"Track B Technical Contradiction Risk: Cosine similarity ({score:.2f}) < 0.75 floor."
            ),
            requires_human_adjudication=True,
        )

    if score < 0.85 or not contract.contains_bounding_parameters:
        return ValidationReport(
            claim_id=contract.claim_id,
            track=OperationalTrack.TRACK_B,
            sil=contract.sil,
            verification_passed=True,
            validation_passed=False,
            flag=AdjudicationFlag.OVERSIMPLIFICATION,
            diagnostic_trace=(
                f"Acceptable simplification or missing bounding parameters "
                f"(similarity={score:.2f}, bounded={contract.contains_bounding_parameters}). "
                "Route to human adjudicator based on target SIL."
            ),
            requires_human_adjudication=True,
        )

    return ValidationReport(
        claim_id=contract.claim_id,
        track=OperationalTrack.TRACK_B,
        sil=contract.sil,
        verification_passed=True,
        validation_passed=True,
        flag=AdjudicationFlag.PASSED,
        diagnostic_trace=f"Track B semantic congruence passed (similarity={score:.2f} >= 0.85).",
        requires_human_adjudication=False,
    )

"""Chamadas ao Claude Code em modo headless (usa a assinatura já logada no `claude`)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .config import LOGS, RAIZ

CLAUDE = shutil.which("claude") or "claude"


class ErroIA(RuntimeError):
    pass


def _extrair_json(texto: str):
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", texto)
    bruto = m.group(1) if m else texto
    ini = min([i for i in (bruto.find("{"), bruto.find("[")) if i >= 0], default=-1)
    if ini < 0:
        raise ErroIA(f"Resposta sem JSON: {texto[:300]}")
    return json.loads(bruto[ini:bruto.rfind("}" if bruto[ini] == "{" else "]") + 1])


def rodar(prompt: str, schema: dict, modelo: str = "sonnet", *, mcp_config: Path | None = None,
          ferramentas: list[str] | None = None, max_turnos: int | None = None, timeout_s: int = 600,
          log_nome: str | None = None) -> tuple[dict, float]:
    """Executa `claude -p` com saída estruturada. Retorna (objeto, custo_usd)."""
    cmd = [CLAUDE, "-p", "--output-format", "json", "--model", modelo, "--json-schema", json.dumps(schema),
           "--no-session-persistence"]
    if mcp_config:
        cmd += ["--mcp-config", str(mcp_config)]
    cmd += ["--strict-mcp-config", "--tools", ""]  # sem ferramentas nativas (Bash, Edit etc.)
    if ferramentas:
        cmd += ["--allowedTools", ",".join(ferramentas), "--permission-mode", "dontAsk"]
    if max_turnos:
        cmd += ["--max-turns", str(max_turnos)]
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                           timeout=timeout_s, cwd=RAIZ)
    except subprocess.TimeoutExpired as e:
        raise ErroIA(f"tempo esgotado ({timeout_s}s)") from e
    if log_nome:
        (LOGS / f"{log_nome}.json").write_text(p.stdout or p.stderr, encoding="utf-8")
    if not p.stdout.strip():
        raise ErroIA(f"claude saiu com código {p.returncode}: {p.stderr[:500]}")
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise ErroIA(f"saída inválida: {p.stdout[:300]}")
    custo = float(d.get("total_cost_usd") or 0)
    if d.get("structured_output") is not None:
        return d["structured_output"], custo
    if d.get("is_error"):
        raise ErroIA(f"{d.get('subtype')}: {str(d.get('result'))[:400]}")
    return _extrair_json(d.get("result") or ""), custo

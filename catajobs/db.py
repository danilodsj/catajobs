from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime

from .config import DB_PATH

# Fluxo de status:
# encontrada -> descartada_regra | triagem
# triagem -> sem_fit | fit
# fit -> personalizada -> aplicada | precisa_humano | falhou | encerrada | nao_elegivel
SCHEMA = """
CREATE TABLE IF NOT EXISTS vagas (
    id TEXT PRIMARY KEY,
    fonte TEXT NOT NULL,
    titulo TEXT NOT NULL,
    empresa TEXT,
    local TEXT,
    modelo_trabalho TEXT,
    url TEXT,
    url_aplicacao TEXT,
    tipo_aplicacao TEXT,
    descricao TEXT,
    publicada_em TEXT,
    encontrada_em TEXT NOT NULL,
    chave_dedup TEXT,
    status TEXT NOT NULL DEFAULT 'encontrada',
    motivo_regra TEXT,
    nota_fit INTEGER,
    motivo_fit TEXT,
    trilha TEXT,
    idioma TEXT,
    avaliada_em TEXT,
    cv_pdf TEXT,
    cv_docx TEXT,
    carta TEXT,
    personalizada_em TEXT,
    tentativas_aplicacao INTEGER DEFAULT 0,
    aplicada_em TEXT,
    resultado_aplicacao TEXT,
    obs_aplicacao TEXT,
    custo_ia_usd REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_status ON vagas(status);
CREATE INDEX IF NOT EXISTS ix_dedup ON vagas(chave_dedup);
CREATE TABLE IF NOT EXISTS execucoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    etapa TEXT,
    inicio TEXT,
    fim TEXT,
    resumo TEXT
);
"""


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def normalizar(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", txt).strip()


# Mesma empresa com nomes diferentes entre fontes (token do Greenhouse/Lever x nome no LinkedIn/Gupy)
ALIASES = {"gympass": "wellhub", "xpinc": "xp", "xp inc": "xp", "xp investimentos": "xp", "c6bank": "c6",
           "c6 bank": "c6", "btgpactual": "btg", "btg pactual": "btg", "inter": "inter", "banco inter": "inter",
           "stone": "stone", "stoneco": "stone", "wildlifestudios": "wildlife", "wildlife studios": "wildlife",
           "rdstation": "rd station", "quintoandar": "quintoandar", "quinto andar": "quintoandar"}
_RUIDO_EMPRESA = r"\b(grupo|group|s ?a|ltda|me|eireli|inc|brasil|brazil|holding|tecnologia|tech|oficial)\b"
_RUIDO_TITULO = (r"\b(grupo|group|pessoa|vaga|sr|senior|pleno|i{1,3}|remoto|remote|hibrido|hybrid|presencial|home office|"
                 r"brasil|brazil|sao paulo|rio de janeiro|sp|rj|exclusiva|afirmativa|banco de talentos)\b")


def normalizar_empresa(empresa: str) -> str:
    e = normalizar(empresa)
    e = ALIASES.get(e, e)
    e = re.sub(_RUIDO_EMPRESA, " ", e)
    e = re.sub(r" +", " ", e).strip()
    return ALIASES.get(e, e)


def chave_dedup(empresa: str, titulo: str) -> str:
    emp = normalizar_empresa(empresa)
    # "(Remote, Curitiba)", "[Banco de Talentos]": local e etiquetas não mudam a vaga
    t = normalizar(re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", titulo or ""))
    for parte in {emp, normalizar(empresa)} - {""}:  # "Grupo QuintoAndar | Growth ..." -> "growth ..."
        t = t.replace(parte, " ")
    t = re.sub(_RUIDO_TITULO, " ", t)
    return f"{emp}|{re.sub(r' +', ' ', t).strip()}"


def normalizar_url(url: str | None) -> str | None:
    """Host + caminho, sem query string, para comparar o destino final da candidatura."""
    if not url:
        return None
    m = re.match(r"https?://(?:www\.)?([^/?#]+)([^?#]*)", url.strip().lower())
    return (m.group(1) + m.group(2).rstrip("/")) if m else None


def duplicada(con: sqlite3.Connection, v: dict, ignorar_id: str | None = None,
              so_aplicadas: bool = False) -> str | None:
    """Retorna o id de uma vaga equivalente já registrada (mesma chave ou mesmo link de candidatura)."""
    filtro = " AND status='aplicada'" if so_aplicadas else ""
    chave = chave_dedup(v.get("empresa", ""), v["titulo"])
    r = con.execute(f"SELECT id FROM vagas WHERE chave_dedup=? AND id<>?{filtro}", (chave, ignorar_id or "")).fetchone()
    if r:
        return r[0]
    url = normalizar_url(v.get("url_aplicacao"))
    if url and "linkedin.com" not in url:
        for (vid, ua) in con.execute(f"SELECT id, url_aplicacao FROM vagas WHERE url_aplicacao IS NOT NULL AND id<>?{filtro}",
                                     (ignorar_id or "",)):
            if normalizar_url(ua) == url:
                return vid
    return None


def inserir_vaga(con: sqlite3.Connection, v: dict) -> bool:
    """Insere se for nova (por id, por empresa+título e por link de candidatura). Retorna True se inseriu."""
    if con.execute("SELECT 1 FROM vagas WHERE id=?", (v["id"],)).fetchone():
        return False
    chave = chave_dedup(v.get("empresa", ""), v["titulo"])
    if duplicada(con, v):
        return False
    campos = ["id", "fonte", "titulo", "empresa", "local", "modelo_trabalho", "url", "url_aplicacao",
              "tipo_aplicacao", "descricao", "publicada_em"]
    valores = [v.get(c) for c in campos] + [agora(), chave]
    con.execute(
        f"INSERT INTO vagas ({','.join(campos)}, encontrada_em, chave_dedup) VALUES ({','.join('?' * (len(campos) + 2))})",
        valores,
    )
    return True


def atualizar(con: sqlite3.Connection, vaga_id: str, **campos) -> None:
    sets = ", ".join(f"{k}=?" for k in campos)
    con.execute(f"UPDATE vagas SET {sets} WHERE id=?", (*campos.values(), vaga_id))
    con.commit()


def registrar_execucao(con: sqlite3.Connection, etapa: str, inicio: str, resumo: str) -> None:
    con.execute("INSERT INTO execucoes (etapa, inicio, fim, resumo) VALUES (?,?,?,?)", (etapa, inicio, agora(), resumo))
    con.commit()

"""Etapas do pipeline: buscar -> avaliar -> personalizar -> aplicar."""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

from . import fontes, ia
from .config import DADOS, PERFIL_NAVEGADOR, busca, curriculo_base, guia_de_voz, perfil, prompt
from .curriculo import gerar_arquivos, texto_plano
from .db import agora, atualizar, chave_dedup, conectar, duplicada, inserir_vaga, registrar_execucao
from .filtros import triar


def _preencher(modelo: str, **kw) -> str:
    for k, v in kw.items():
        modelo = modelo.replace("{" + k + "}", str(v))
    return modelo


def log(msg: str) -> None:
    print(f"[{agora()}] {msg}", flush=True)


# ====================================================================== BUSCAR
def retriar() -> dict:
    """Reaplica o filtro por regras nas vagas ainda não avaliadas pela IA (após mudar busca.yaml)."""
    cfg, con = busca(), conectar()
    mudou = 0
    for r in con.execute("SELECT * FROM vagas WHERE status IN ('triagem','descartada_regra')").fetchall():
        passa, motivo = triar(dict(r), cfg)
        novo = "triagem" if passa else "descartada_regra"
        if novo != r["status"] or motivo != r["motivo_regra"]:
            mudou += novo != r["status"]
            atualizar(con, r["id"], status=novo, motivo_regra=motivo)
    log(f"retriagem: {mudou} vagas mudaram de status")
    return {"mudaram": mudou}


def buscar(janela_horas: int | None = None) -> dict:
    cfg, inicio = busca(), agora()
    con = conectar()
    primeira = con.execute("SELECT COUNT(*) FROM vagas").fetchone()[0] == 0
    f = cfg["fontes"]
    janela = janela_horas or (f["linkedin_janela_horas_primeira_execucao"] if primeira else f["linkedin_janela_horas_diaria"])
    brutas: list[dict] = []

    dias = f.get("gupy_dias_maximos_publicacao", 21)
    amplos = cfg.get("termos_amplos") or []
    termos_br = list(dict.fromkeys(cfg["termos"] + amplos))

    def coletar(nome: str, fn, itens):
        nonlocal brutas
        for x in itens:
            try:
                r = fn(x)
            except Exception as e:  # uma fonte fora do ar não derruba a busca
                log(f"{nome} '{x}': erro {e}")
                continue
            log(f"{nome} '{x}': {len(r)}")
            brutas += r

    if f.get("gupy"):
        coletar("gupy", lambda t: fontes.gupy(t, dias), termos_br)
    if f.get("remotar"):
        coletar("remotar", lambda t: fontes.remotar(t, dias), amplos or cfg["termos"])
    if f.get("vagascom"):
        coletar("vagas.com", fontes.vagascom, termos_br)
    rem = f.get("remotas_internacionais") or {}
    if rem.get("ativo"):
        termos_en = rem.get("termos") or []
        coletar("himalayas", fontes.himalayas, termos_en)
        coletar("remotive", fontes.remotive, termos_en)
        coletar("jobicy", fontes.jobicy, rem.get("tags") or [])
        coletar("remoteok", fontes.remoteok, rem.get("tags") or [])
    if f.get("linkedin"):
        for t in cfg["termos"]:
            r = fontes.linkedin(t, cfg["localizacao"]["linkedin_geo_id"], janela, f["linkedin_paginas_por_termo"])
            log(f"linkedin '{t}': {len(r)}")
            brutas += r
    for token in f.get("greenhouse") or []:
        r = fontes.greenhouse(token)
        log(f"greenhouse {token}: {len(r)}")
        brutas += r
    for emp in f.get("lever") or []:
        r = fontes.lever(emp)
        log(f"lever {emp}: {len(r)}")
        brutas += r
    coletar("ashby", fontes.ashby, f.get("ashby") or [])
    brutas += _google_vagas(f.get("google_vagas") or {})

    novas = triagem = descartadas = 0
    detalhes = {"linkedin": 0, "vagascom": 0}
    max_detalhes = {"linkedin": f.get("linkedin_detalhes_por_execucao", 150),
                    "vagascom": f.get("vagascom_detalhes_por_execucao", 150)}
    vistos = set()
    for v in brutas:
        if v["id"] in vistos or not v["titulo"]:
            continue
        vistos.add(v["id"])
        if con.execute("SELECT 1 FROM vagas WHERE id=?", (v["id"],)).fetchone():
            continue
        passa, motivo = triar(v, cfg)
        fonte = v["fonte"]
        if passa and fonte in detalhes and v["descricao"] is None and detalhes[fonte] < max_detalhes[fonte]:
            detalhes[fonte] += 1
            v = fontes.detalhar(v)
            passa, motivo = triar(v, cfg)  # reavalia com descrição e modelo de trabalho
        if inserir_vaga(con, v):
            novas += 1
            if passa:
                triagem += 1
                atualizar(con, v["id"], status="triagem", motivo_regra=motivo)
            else:
                descartadas += 1
                atualizar(con, v["id"], status="descartada_regra", motivo_regra=motivo)
    con.commit()
    resumo = {"coletadas": len(vistos), "novas": novas, "para_triagem_ia": triagem, "descartadas_regra": descartadas,
              "linkedin_limitado": fontes.LINKEDIN_BLOQUEADO}
    registrar_execucao(con, "buscar", inicio, json.dumps(resumo))
    log(f"busca: {resumo}")
    return resumo


def _google_vagas(cfg_g: dict) -> list[dict]:
    """Google Vagas pela SerpApi, em rodízio de consultas, sem passar da cota do mês."""
    import calendar
    from datetime import date

    from .config import DADOS, segredo
    chave = segredo("serpapi_api_key")
    consultas = cfg_g.get("consultas") or []
    if not cfg_g.get("ativo") or not chave or not consultas:
        return []
    restante = fontes.serpapi_cota(chave)
    hoje = date.today()
    dias_restantes = calendar.monthrange(hoje.year, hoje.month)[1] - hoje.day + 1
    # divide o que sobrou da cota pelos dias que faltam no mês, guardando uma reserva
    n = min(cfg_g.get("buscas_por_execucao", 8), max(0, restante - cfg_g.get("reserva", 10)) // dias_restantes)
    if n <= 0:
        log(f"google vagas: cota da SerpApi no limite ({restante} restantes), pulei nesta execução")
        return []
    ponteiro = DADOS / "serpapi_ponteiro.txt"
    ini = int(ponteiro.read_text()) if ponteiro.exists() else 0
    vagas = []
    for i in range(n):
        c = consultas[(ini + i) % len(consultas)]
        r = fontes.google_vagas(c, chave)
        log(f"google vagas '{c['q']}' ({c.get('local', 'Brazil')}{', remoto' if c.get('remoto') else ''}): {len(r)}")
        vagas += r
    ponteiro.write_text(str((ini + n) % len(consultas)))
    log(f"google vagas: {n} buscas usadas, cota restante {restante - n}")
    return vagas


def completar_descricoes(limite: int = 120) -> int:
    """Busca a descrição das vagas que ficaram sem detalhe (LinkedIn limita a taxa; vagas.com tem teto por execução)."""
    cfg, con = busca(), conectar()
    pend = [dict(r) for r in con.execute(
        "SELECT * FROM vagas WHERE fonte IN ('linkedin','vagascom') AND descricao IS NULL AND status='triagem' "
        "ORDER BY encontrada_em DESC LIMIT ?", (limite,))]
    ok = 0
    for v in pend:
        if v["fonte"] == "linkedin" and fontes.LINKEDIN_BLOQUEADO:
            continue  # o LinkedIn limitou nesta execução; as do vagas.com seguem
        v = fontes.detalhar(v)
        if v.get("descricao") is None:
            continue
        passa, motivo = triar(v, cfg)
        atualizar(con, v["id"], descricao=v["descricao"], modelo_trabalho=v["modelo_trabalho"],
                  url_aplicacao=v["url_aplicacao"], tipo_aplicacao=v["tipo_aplicacao"],
                  status="triagem" if passa else "descartada_regra", motivo_regra=motivo)
        ok += 1
    log(f"descrições completadas: {ok} de {len(pend)}")
    return ok



# ================================================================ PERFIL-ALVO
# Padrão usado quando config/busca.yaml não tem a seção `perfil_alvo` (o onboarding preenche essa seção).
PERFIL_ALVO_PADRAO = {
    "especialidade": "marketing, dados e inteligência artificial",
    "areas": "marketing (digital, growth, performance, CRM, mídia, marca), dados (analytics, BI, inteligência de "
             "mercado, ciência de dados aplicada a negócio) e inteligência artificial (IA generativa, automação, "
             "produtos de IA).",
    "nivel": "analista sênior para cima. Aceita: Analista Sênior, Especialista, Coordenador(a), Gerente, Head, Lead, "
             "Product Manager.",
    "rejeitar": "nível júnior ou pleno (mesmo que o título não diga, confira na descrição: anos de experiência pedidos "
                "abaixo de 4 indica pleno), estágio, cargos puramente de engenharia de software, vendas, atendimento, "
                "design gráfico, áreas sem relação.",
    "observacoes": "- Product Manager só entra quando o produto ou o time é de marketing, dados, IA, growth, martech ou "
                   "analytics. PM de produto genérico (pagamentos, logística, app, plataforma interna sem foco em "
                   "dados/IA/marketing) é sem fit.",
    "trilhas": ["marketing", "dados", "ia", "produto"],
}


def perfil_alvo() -> dict:
    return {**PERFIL_ALVO_PADRAO, **{k: v for k, v in (busca().get("perfil_alvo") or {}).items() if v not in (None, "")}}


def _cidades_texto(cidades: list[str]) -> str:
    return cidades[0] if len(cidades) == 1 else ", ".join(cidades[:-1]) + " ou " + cidades[-1]


def regra_local() -> tuple[str, str, str]:
    """Regra de local para os prompts: (avaliação, candidatura, motivo curto quando o local não serve)."""
    loc = busca()["localizacao"]
    cidade = perfil().get("cidade") or "Brasil"
    cidades = loc.get("cidades_presencial_hibrido") or []
    remoto = loc.get("aceita_remoto", True)
    sem_remoto = " Não aceita vaga 100% remota: vaga remota fica com nota abaixo de 40." if not remoto else ""
    if not loc.get("aceita_presencial_hibrido", True):
        return (f"O candidato mora em {cidade} e só aceita vaga 100% remota. `na_cidade_aceita` é sempre false. "
                "Vaga que não seja \"remoto\" fica com nota abaixo de 40.",
                "O candidato só aceita vaga 100% remota. Se a vaga for híbrida ou presencial, não se candidate: retorne "
                "`nao_elegivel` com a observação \"não é remota\".",
                "Não é remota")
    if not cidades:
        return (f"O candidato mora em {cidade} e aceita vaga remota, híbrida ou presencial em qualquer cidade do Brasil. "
                f"`na_cidade_aceita` é true para qualquer local no Brasil.{sem_remoto}",
                "O candidato aceita vaga remota, híbrida ou presencial em qualquer cidade do Brasil."
                + (" Não aceita vaga 100% remota: se for, retorne `nao_elegivel`." if not remoto else ""),
                "Local não aceito")
    c = _cidades_texto(cidades)
    if remoto:
        aval = (f"O candidato mora em {cidade}. Em {c} aceita remoto, híbrido ou presencial. Fora disso, só aceita vaga "
                f"100% remota.\n`na_cidade_aceita` é true quando o local de trabalho é {c} (a cidade, não outras "
                f"cidades do mesmo estado).\nVaga fora de {c} que não seja \"remoto\" fica com nota abaixo de 40.")
        apl = (f"O candidato só aceita vaga fora de {c} se for 100% remota. Ao abrir a vaga, confira o local e o modelo "
               "de trabalho mostrados na página (ex.: selo \"Remoto\", \"Híbrido\", \"Presencial\" no LinkedIn ou na "
               f"Gupy). Se a vaga for híbrida ou presencial fora de {c}, não se candidate: retorne `nao_elegivel` com a "
               f"observação \"fora de {c} e não é remota\".")
    else:
        aval = (f"O candidato mora em {cidade} e só aceita vaga híbrida ou presencial em {c}.\n`na_cidade_aceita` é "
                f"true quando o local de trabalho é {c}.{sem_remoto}\nVaga fora de {c} fica com nota abaixo de 40.")
        apl = (f"O candidato só aceita vaga híbrida ou presencial em {c}. Vaga remota ou em outra cidade: retorne "
               f"`nao_elegivel` com a observação \"fora de {c}\".")
    return aval, apl, f"Fora de {c} e não é remota"


# ====================================================================== AVALIAR
SCHEMA_AVALIACAO = {
    "type": "object",
    "properties": {
        "avaliacoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "nota": {"type": "integer", "minimum": 0, "maximum": 100},
                    "trilha": {"type": "string", "enum": ["marketing", "dados", "ia", "produto", "outra"]},
                    "idioma": {"type": "string", "enum": ["pt", "en"]},
                    "modelo_trabalho": {"type": "string", "enum": ["remoto", "hibrido", "presencial", "indefinido"]},
                    "na_cidade_aceita": {"type": "boolean"},
                    "motivo": {"type": "string"},
                },
                "required": ["id", "nota", "trilha", "idioma", "modelo_trabalho", "na_cidade_aceita", "motivo"],
            },
        }
    },
    "required": ["avaliacoes"],
}


def _avaliar_lote(lote: list[dict], cv: str, modelo: str) -> tuple[list[dict], float]:
    blocos = []
    for v in lote:
        desc = (v["descricao"] or "")[:3500]
        blocos.append(f"<vaga id=\"{v['id']}\">\nTítulo: {v['titulo']}\nEmpresa: {v['empresa']}\n"
                      f"Local: {v['local']} ({v['modelo_trabalho'] or 'modelo não informado'})\n{desc}\n</vaga>")
    alvo = perfil_alvo()
    trilhas = [str(x) for x in alvo["trilhas"]]
    p = _preencher(prompt("avaliar"), especialidade=alvo["especialidade"], areas=alvo["areas"], nivel=alvo["nivel"],
                   rejeitar=alvo["rejeitar"], observacoes=(alvo.get("observacoes") or "").strip() + "\n",
                   regra_local=regra_local()[0], trilhas=", ".join(f'"{x}"' for x in trilhas),
                   curriculo=cv, vagas="\n\n".join(blocos))
    schema = json.loads(json.dumps(SCHEMA_AVALIACAO))
    schema["properties"]["avaliacoes"]["items"]["properties"]["trilha"]["enum"] = [*trilhas, "outra"]
    r, custo = ia.rodar(p, schema, modelo, timeout_s=600)
    return r["avaliacoes"], custo


def avaliar(paralelo: int = 3) -> dict:
    cfg, inicio, cv = busca(), agora(), curriculo_base()
    con = conectar()
    pend = [dict(r) for r in con.execute(
        "SELECT * FROM vagas WHERE status='triagem' AND (descricao IS NOT NULL OR encontrada_em < datetime('now','-3 days')) "
        "ORDER BY encontrada_em")]
    n = cfg["limites"]["avaliacoes_por_lote"]
    lotes = [pend[i:i + n] for i in range(0, len(pend), n)]
    minimo = cfg["filtros"]["nota_minima_fit"]
    fit = sem_fit = erros = 0
    custo_total = 0.0
    log(f"avaliando {len(pend)} vagas em {len(lotes)} lotes")
    with ThreadPoolExecutor(max_workers=paralelo) as ex:
        futuros = {ex.submit(_avaliar_lote, l, cv, cfg["modelos_ia"]["avaliacao"]): l for l in lotes}
        for fut in as_completed(futuros):
            lote = futuros[fut]
            try:
                avaliacoes, custo = fut.result()
            except Exception as e:  # noqa: BLE001
                erros += len(lote)
                log(f"erro no lote: {e}")
                continue
            custo_total += custo
            por_id = {a["id"]: a for a in avaliacoes}
            for v in lote:
                a = por_id.get(v["id"])
                if not a:
                    continue
                local_ok = a["na_cidade_aceita"] or a["modelo_trabalho"] == "remoto"
                ok = a["nota"] >= minimo and a["trilha"] != "outra" and local_ok
                motivo = a["motivo"] if local_ok else f"{regra_local()[2]} ({a['modelo_trabalho']}). {a['motivo']}"
                fit += ok
                sem_fit += not ok
                status = ("personalizada" if v["cv_pdf"] else "fit") if ok else "sem_fit"
                modelo = a["modelo_trabalho"] if a["modelo_trabalho"] != "indefinido" else v["modelo_trabalho"]
                atualizar(con, v["id"], status=status, nota_fit=a["nota"], motivo_fit=motivo, modelo_trabalho=modelo,
                          trilha=a["trilha"], idioma=a["idioma"], avaliada_em=agora(),
                          custo_ia_usd=(v["custo_ia_usd"] or 0) + custo / max(len(lote), 1))
    resumo = {"avaliadas": fit + sem_fit, "fit": fit, "sem_fit": sem_fit, "erros": erros, "custo_usd": round(custo_total, 2)}
    registrar_execucao(con, "avaliar", inicio, json.dumps(resumo))
    log(f"avaliação: {resumo}")
    return resumo


# ====================================================================== PERSONALIZAR
SCHEMA_CV = {
    "type": "object",
    "properties": {
        "titulo_profissional": {"type": "string"},
        "resumo": {"type": "string"},
        "competencias": {"type": "array", "items": {"type": "string"}},
        "experiencias": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cargo": {"type": "string"}, "empresa": {"type": "string"}, "local": {"type": "string"},
                    "periodo": {"type": "string"}, "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["cargo", "empresa", "periodo", "bullets"],
            },
        },
        "formacao": {
            "type": "array",
            "items": {"type": "object", "properties": {"curso": {"type": "string"}, "instituicao": {"type": "string"},
                                                        "periodo": {"type": "string"}},
                      "required": ["curso", "instituicao"]},
        },
        "certificacoes": {"type": "array", "items": {"type": "string"}},
        "idiomas": {"type": "array", "items": {"type": "string"}},
        "ferramentas": {"type": "array", "items": {"type": "string"}},
        "carta": {"type": "string"},
        "por_que_esta_vaga": {"type": "string"},
        "sobre_voce": {"type": "string"},
    },
    "required": ["titulo_profissional", "resumo", "competencias", "experiencias", "formacao", "idiomas", "carta",
                 "por_que_esta_vaga", "sobre_voce"],
}


def personalizar_vaga(v: dict, cv: str, voz: str, modelo: str) -> tuple[dict, float]:
    p = _preencher(prompt("personalizar"), idioma=v.get("idioma") or "pt", voz=voz, titulo=v["titulo"],
                   empresa=v["empresa"], local=v["local"], descricao=(v["descricao"] or "")[:8000], curriculo=cv)
    return ia.rodar(p, SCHEMA_CV, modelo, timeout_s=900)


def personalizar(limite: int | None = None, paralelo: int = 3) -> dict:
    cfg, inicio, cv, voz = busca(), agora(), curriculo_base(), guia_de_voz()
    limite = limite or cfg["limites"]["aplicacoes_por_dia"]
    con = conectar()
    pend = [dict(r) for r in con.execute(
        "SELECT * FROM vagas WHERE status='fit' ORDER BY nota_fit DESC, encontrada_em DESC LIMIT ?", (limite,))]
    ok = erros = 0
    custo_total = 0.0
    log(f"personalizando {len(pend)} vagas")
    with ThreadPoolExecutor(max_workers=paralelo) as ex:
        futuros = {ex.submit(personalizar_vaga, v, cv, voz, cfg["modelos_ia"]["personalizacao"]): v for v in pend}
        for fut in as_completed(futuros):
            v = futuros[fut]
            try:
                dados, custo = fut.result()
                pdf, docx, js = gerar_arquivos(v, dados, perfil())
            except Exception as e:  # noqa: BLE001
                erros += 1
                log(f"erro ao personalizar {v['id']}: {e}")
                continue
            custo_total += custo
            ok += 1
            atualizar(con, v["id"], status="personalizada", cv_pdf=str(pdf), cv_docx=str(docx), carta=dados["carta"],
                      personalizada_em=agora(), custo_ia_usd=(v["custo_ia_usd"] or 0) + custo)
            log(f"personalizada: {v['titulo']} | {v['empresa']}")
    resumo = {"personalizadas": ok, "erros": erros, "custo_usd": round(custo_total, 2)}
    registrar_execucao(con, "personalizar", inicio, json.dumps(resumo))
    log(f"personalização: {resumo}")
    return resumo


# ====================================================================== APLICAR
SCHEMA_APLICACAO = {
    "type": "object",
    "properties": {
        "status": {"type": "string",
                   "enum": ["aplicada", "ja_aplicada", "precisa_humano", "encerrada", "nao_elegivel", "falhou",
                            "simulada"]},
        "plataforma": {"type": "string"},
        "observacoes": {"type": "string"},
        "link_formulario": {"type": "string", "description": "URL da página onde está o formulário de candidatura"},
        "perguntas": {"type": "array", "items": {"type": "object", "properties": {
            "pergunta": {"type": "string"}, "resposta": {"type": "string"}}}},
    },
    "required": ["status", "plataforma", "observacoes"],
}


def _mcp_config() -> str:
    cfg = busca()
    args = ["-y", "@playwright/mcp@latest", "--user-data-dir", str(PERFIL_NAVEGADOR),
            "--output-dir", str(DADOS / "playwright"), "--viewport-size", "1366,900"]
    if cfg["navegador"].get("headless"):
        args.append("--headless")
    caminho = DADOS / "mcp-aplicacao.json"
    caminho.write_text(json.dumps({"mcpServers": {"playwright": {"type": "stdio", "command": "npx", "args": args}}},
                                  indent=2), encoding="utf-8")
    return str(caminho)


def _liberar_navegador() -> None:
    """Fecha Chrome que tenha ficado aberto com o perfil do robô (só esse perfil, nunca o Chrome pessoal)."""
    import subprocess
    alvo = str(PERFIL_NAVEGADOR).replace("'", "''")
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
          f"Where-Object {{ $_.CommandLine -and $_.CommandLine.Contains('{alvo}') }} | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    conta = ("@(Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
             f"Where-Object {{ $_.CommandLine -and $_.CommandLine.Contains('{alvo}') }}).Count")
    # Stop-Process não espera o Chrome morrer: aguarda os processos sumirem e a trava do perfil ("lockfile") soltar.
    for _ in range(30):
        try:  # o PowerShell às vezes demora; um travamento aqui não pode derrubar a candidatura
            vivos = subprocess.run(["powershell", "-NoProfile", "-Command", f"{ps}; {conta}"],
                                   capture_output=True, text=True, timeout=90).stdout
        except (subprocess.TimeoutExpired, OSError):
            vivos = "?"
        livre = True
        for nome in ("lockfile", "SingletonLock", "SingletonCookie", "SingletonSocket"):
            try:
                (PERFIL_NAVEGADOR / nome).unlink(missing_ok=True)
            except OSError:
                livre = False
        if livre and vivos.strip() in ("", "0"):
            return
        time.sleep(1)
    log("aviso: o perfil do navegador continua preso depois de 30s")


def _perfil_para_prompt() -> str:
    p = dict(perfil())
    p.pop("permitir_criar_conta", None)
    return yaml.safe_dump(p, allow_unicode=True, sort_keys=False)


def _regra_conta() -> str:
    senha = os.environ.get("CATAJOBS_SENHA_ATS")
    if perfil().get("permitir_criar_conta") and senha:
        return (f"crie a conta com o e-mail do candidato e a senha `{senha}`. "
                "Se pedir confirmação por e-mail ou SMS, retorne `precisa_humano`.")
    return "não crie conta. Retorne `precisa_humano` com a observação \"exige cadastro no site\"."


MODO_REAL = "Envio real: conclua e envie a candidatura."
MODO_SIMULACAO = ("SIMULAÇÃO: preencha o formulário inteiro e anexe o currículo, mas NÃO clique no botão final de "
                  "enviar/finalizar candidatura. Pare na revisão e retorne status `simulada`, descrevendo em "
                  "`observacoes` o que preencheu e o que ficaria pendente.")


def aplicar_vaga(v: dict, simular: bool = False) -> tuple[dict, float]:
    cfg = busca()
    js = json.loads(Path(v["cv_pdf"]).with_suffix(".json").read_text(encoding="utf-8"))
    p = _preencher(
        prompt("aplicar"), titulo=v["titulo"], empresa=v["empresa"], plataforma=v["tipo_aplicacao"] or "desconhecida",
        url_aplicacao=v["url_aplicacao"] or v["url"], url=v["url"], cv_pdf=v["cv_pdf"], cv_docx=v["cv_docx"],
        perfil=_perfil_para_prompt(), carta=js["carta"], por_que=js["por_que_esta_vaga"], sobre_voce=js["sobre_voce"],
        curriculo_texto=texto_plano(js, perfil(), js.get("idioma", "pt")), regra_conta=_regra_conta(),
        regra_local_aplicacao=regra_local()[1],
        modo=MODO_SIMULACAO if simular else MODO_REAL,
    )
    lim = cfg["limites"]
    _liberar_navegador()
    return ia.rodar(p, SCHEMA_APLICACAO, cfg["modelos_ia"]["aplicacao"], mcp_config=_mcp_config(),
                    ferramentas=["mcp__playwright"], max_turnos=lim["max_turnos_agente_aplicacao"],
                    timeout_s=lim["tempo_maximo_por_aplicacao_min"] * 60,
                    log_nome=f"aplicacao_{v['id']}")


def aplicar(limite: int | None = None, ids: list[str] | None = None, simular: bool = False) -> dict:
    """Candidaturas em sequência (um navegador logado, uma vaga por vez)."""
    cfg, inicio = busca(), agora()
    con = conectar()
    hoje = agora()[:10]
    feitas_hoje = con.execute("SELECT COUNT(*) FROM vagas WHERE status='aplicada' AND substr(aplicada_em,1,10)=?",
                              (hoje,)).fetchone()[0]
    limite = limite if limite is not None else max(cfg["limites"]["aplicacoes_por_dia"] - feitas_hoje, 0)
    if ids:
        pend = [dict(r) for r in con.execute(
            f"SELECT * FROM vagas WHERE id IN ({','.join('?' * len(ids))})", ids)]
    else:
        pend = [dict(r) for r in con.execute(
            "SELECT * FROM vagas WHERE status='personalizada' AND tentativas_aplicacao < 2 "
            "ORDER BY nota_fit DESC LIMIT ?", (limite,))]
    contagem: dict[str, int] = {}
    custo_total = 0.0
    log(f"aplicando em {len(pend)} vagas")
    for v in pend:
        igual = duplicada(con, v, ignorar_id=v["id"], so_aplicadas=True)
        if igual and not simular:
            atualizar(con, v["id"], status="duplicada", obs_aplicacao=f"Mesma vaga já inscrita: {igual}")
            contagem["duplicada"] = contagem.get("duplicada", 0) + 1
            log(f"-- duplicada, pulando: {v['titulo']} | {v['empresa']} (igual a {igual})")
            continue
        log(f"-> {v['titulo']} | {v['empresa']} | {v['tipo_aplicacao']}")
        try:
            r, custo = aplicar_vaga(v, simular)
        except Exception as e:  # noqa: BLE001
            r, custo = {"status": "falhou", "plataforma": v["tipo_aplicacao"] or "", "observacoes": str(e)[:500]}, 0.0
        custo_total += custo
        if simular:
            contagem[r["status"]] = contagem.get(r["status"], 0) + 1
            log(f"   [simulação] {r['status']}: {r.get('observacoes', '')[:300]}")
            continue
        st = "aplicada" if r["status"] in ("aplicada", "ja_aplicada") else r["status"]
        tentativas = (v["tentativas_aplicacao"] or 0) + 1
        obs = (r.get("observacoes") or "").lower()
        if st == "falhou" and any(x in obs for x in ("em uso", "already in use", "connect_timeout", "não conectou")):
            tentativas -= 1  # problema do navegador local, não da vaga: não gasta tentativa
            _liberar_navegador()
        if st == "falhou" and tentativas < 2:
            st = "personalizada"  # tenta de novo na próxima execução
        if r.get("link_formulario", "").startswith("http"):
            v["url_aplicacao"] = r["link_formulario"]
        atualizar(con, v["id"], status=st, tentativas_aplicacao=tentativas, url_aplicacao=v["url_aplicacao"],
                  aplicada_em=agora() if st == "aplicada" else v["aplicada_em"],
                  resultado_aplicacao=r["status"], obs_aplicacao=r.get("observacoes", ""),
                  custo_ia_usd=(v["custo_ia_usd"] or 0) + custo)
        contagem[r["status"]] = contagem.get(r["status"], 0) + 1
        log(f"   {r['status']}: {r.get('observacoes', '')[:160]}")
    resumo = {"tentativas": len(pend), **contagem, "custo_usd": round(custo_total, 2)}
    registrar_execucao(con, "aplicar", inicio, json.dumps(resumo))
    log(f"aplicação: {resumo}")
    return resumo

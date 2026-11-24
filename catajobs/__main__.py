"""Uso: python -m catajobs <comando>

  onboarding      perguntas guiadas para criar ou revisar o perfil (salva a cada resposta)
  diario          roda tudo: buscar, avaliar, personalizar, aplicar, dashboard
  buscar          coleta vagas novas e aplica o filtro por regras
  avaliar         nota de fit por IA para as vagas filtradas
  personalizar    gera CV ATS + carta para as vagas com fit
  aplicar         faz as candidaturas pelo navegador (Playwright MCP)
  dashboard       regenera dashboard.html
  modelos         gera os modelos ATS base por trilha (marketing, dados, ia, produto) em modelos/
  login           abre o navegador do robô para você logar no LinkedIn, Gupy e outros sites
  reabrir         devolve as vagas "precisa de você" para a fila de candidatura
  retriar         reaplica o filtro por regras depois de mudar config/busca.yaml
  status          resumo no terminal
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from . import dashboard, etapas
from .config import PERFIL_NAVEGADOR, RAIZ, curriculo_base, perfil
from .db import conectar


def _login():
    PERFIL_NAVEGADOR.mkdir(parents=True, exist_ok=True)
    chrome = next((c for c in (shutil.which("chrome"),
                               r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                               r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if c and
                   __import__("os").path.exists(c)), None)
    if not chrome:
        sys.exit("Google Chrome não encontrado. Instale o Chrome (o Playwright MCP usa o Chrome por padrão).")
    sites = ["https://www.linkedin.com/login", "https://login.gupy.io/candidates/signin", "https://accounts.google.com"]
    print("Faça login nos sites abertos e feche o navegador quando terminar.")
    subprocess.run([chrome, f"--user-data-dir={PERFIL_NAVEGADOR}", "--no-first-run", *sites])


def _modelos():
    from .curriculo import gerar_arquivos
    cv, p = curriculo_base(), perfil()
    trilhas = {
        "marketing": "Coordenador(a) / Especialista de Marketing Digital e Growth. Performance, CRM, mídia paga, "
                     "funil, análise de dados de marketing, experimentação, gestão de time.",
        "dados": "Analista Sênior / Coordenador(a) de Dados e BI. SQL, Python, modelagem, dashboards, "
                 "inteligência de mercado, métricas de negócio, governança, stakeholders.",
        "ia": "Especialista / Coordenador(a) de Inteligência Artificial aplicada a negócio. IA generativa, LLMs, "
              "agentes, automação, casos de uso, adoção, prompt engineering, dados.",
        "produto": "Product Manager de Dados, Growth ou IA. Discovery, roadmap, métricas de produto, "
                   "experimentação, produtos de dados e IA, times multidisciplinares.",
    }
    for idioma in ("pt", "en"):
        for nome, desc in trilhas.items():
            vaga = {"id": f"modelo:{nome}:{idioma}", "titulo": f"Modelo {nome}", "empresa": "", "local": "Brasil",
                    "descricao": desc, "idioma": idioma}
            dados, _ = etapas.personalizar_vaga(vaga, cv, "", "sonnet")
            pdf, *_ = gerar_arquivos(vaga, dados, p, RAIZ / "modelos" / f"{nome}_{idioma}")
            print("modelo:", pdf)


def _status():
    con = conectar()
    for s, q in con.execute("SELECT status, COUNT(*) FROM vagas GROUP BY status ORDER BY 2 DESC"):
        print(f"{s:20} {q}")


def main():
    ap = argparse.ArgumentParser(prog="catajobs", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comando", choices=["diario", "buscar", "avaliar", "personalizar", "aplicar", "dashboard",
                                        "modelos", "login", "reabrir", "status", "retriar", "onboarding"])
    ap.add_argument("--janela-horas", type=int, help="buscar: idade máxima das vagas do LinkedIn, em horas")
    ap.add_argument("--limite", type=int, help="máximo de vagas na etapa")
    ap.add_argument("--ids", nargs="*", help="ids específicos para aplicar")
    ap.add_argument("--sem-aplicar", action="store_true", help="no diário, para antes das candidaturas")
    ap.add_argument("--simular", action="store_true", help="aplicar: preenche os formulários sem enviar")
    a = ap.parse_args()

    if a.comando == "onboarding":
        from .onboarding import main as onboarding
        return onboarding()
    if a.comando == "login":
        return _login()
    if a.comando == "modelos":
        return _modelos()
    if a.comando == "status":
        return _status()
    if a.comando == "reabrir":
        con = conectar()
        n = con.execute("UPDATE vagas SET status='personalizada', tentativas_aplicacao=0 "
                        "WHERE status='precisa_humano'").rowcount
        con.commit()
        print(f"{n} vagas voltaram para a fila")
        return dashboard.gerar()
    if a.comando == "retriar":
        etapas.retriar()
        return dashboard.gerar()
    try:
        if a.comando in ("diario", "buscar"):
            etapas.buscar(a.janela_horas)
            etapas.completar_descricoes()
        if a.comando in ("diario", "avaliar"):
            etapas.avaliar()
        if a.comando in ("diario", "personalizar"):
            etapas.personalizar(a.limite)
        if a.comando == "aplicar" or (a.comando == "diario" and not a.sem_aplicar):
            etapas.aplicar(a.limite, a.ids, a.simular)
    finally:
        print("dashboard:", dashboard.gerar())


if __name__ == "__main__":
    main()

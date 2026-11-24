"""Renderiza o currículo ATS (uma coluna, texto real, títulos padrão) em PDF e DOCX."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from fpdf import FPDF

from .config import SAIDA
from .db import normalizar

TITULOS = {
    "pt": {"resumo": "RESUMO PROFISSIONAL", "competencias": "COMPETÊNCIAS", "experiencia": "EXPERIÊNCIA PROFISSIONAL",
           "formacao": "FORMAÇÃO ACADÊMICA", "certificacoes": "CERTIFICAÇÕES E CURSOS", "idiomas": "IDIOMAS",
           "ferramentas": "FERRAMENTAS", "arquivo": "Curriculo"},
    "en": {"resumo": "PROFESSIONAL SUMMARY", "competencias": "CORE SKILLS", "experiencia": "PROFESSIONAL EXPERIENCE",
           "formacao": "EDUCATION", "certificacoes": "CERTIFICATIONS", "idiomas": "LANGUAGES",
           "ferramentas": "TOOLS", "arquivo": "Resume"},
}
FONTES = Path(r"C:\Windows\Fonts")


def _limpar(t: str) -> str:
    # ATS e a voz do usuário: sem travessão
    return re.sub(r"\s*[—–]\s*", ", ", (t or "").strip())


def _contato(p: dict) -> str:
    local = ", ".join(x for x in (p.get("cidade"), p.get("estado")) if x)
    return " | ".join(x for x in (local, p.get("telefone"), p.get("email"), p.get("linkedin"), p.get("portfolio")) if x)


def texto_plano(d: dict, p: dict, idioma: str = "pt") -> str:
    t = TITULOS.get(idioma, TITULOS["pt"])
    linhas = [p.get("nome_completo", ""), d["titulo_profissional"], _contato(p), "", t["resumo"], d["resumo"], "",
              t["competencias"], " | ".join(d["competencias"]), "", t["experiencia"]]
    for e in d["experiencias"]:
        linhas += [f"{e['cargo']}, {e['empresa']}" + (f", {e['local']}" if e.get("local") else ""), e["periodo"]]
        linhas += [f"- {b}" for b in e["bullets"]] + [""]
    linhas.append(t["formacao"])
    linhas += [", ".join(x for x in (f["curso"], f["instituicao"], f.get("periodo")) if x) for f in d["formacao"]]
    if d.get("certificacoes"):
        linhas += ["", t["certificacoes"], *d["certificacoes"]]
    if d.get("ferramentas"):
        linhas += ["", t["ferramentas"], ", ".join(d["ferramentas"])]
    linhas += ["", t["idiomas"], " | ".join(d["idiomas"])]
    return _limpar("\n".join(linhas)).replace(", \n", "\n")


# ------------------------------------------------------------------ PDF
class _PDF(FPDF):
    def __init__(self):
        super().__init__(format="A4")
        self.set_margins(18, 15, 18)
        self.set_auto_page_break(True, 15)
        self.add_font("Arial", "", str(FONTES / "arial.ttf"))
        self.add_font("Arial", "B", str(FONTES / "arialbd.ttf"))
        self.add_font("Arial", "I", str(FONTES / "ariali.ttf"))

    def secao(self, titulo: str):
        self.ln(3)
        self.set_font("Arial", "B", 11)
        self.set_text_color(20, 20, 20)
        self.cell(0, 6, titulo, new_x="LMARGIN", new_y="NEXT")
        y = self.get_y()
        self.set_draw_color(120, 120, 120)
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(1.5)

    def paragrafo(self, texto: str, tam: float = 10, estilo: str = ""):
        self.set_font("Arial", estilo, tam)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 4.8, _limpar(texto), new_x="LMARGIN", new_y="NEXT")

    def bullet(self, texto: str):
        self.set_font("Arial", "", 10)
        self.set_x(self.l_margin + 2)
        self.cell(4, 4.8, "•")
        self.multi_cell(0, 4.8, _limpar(texto), new_x="LMARGIN", new_y="NEXT")


def _pdf(d: dict, p: dict, idioma: str, destino: Path) -> None:
    t = TITULOS.get(idioma, TITULOS["pt"])
    pdf = _PDF()
    pdf.set_title(f"{p.get('nome_completo', '')} - {d['titulo_profissional']}")
    pdf.set_author(p.get("nome_completo", ""))
    pdf.add_page()
    pdf.set_font("Arial", "B", 17)
    pdf.cell(0, 8, p.get("nome_completo", ""), new_x="LMARGIN", new_y="NEXT")
    pdf.paragrafo(d["titulo_profissional"], 11, "B")
    pdf.paragrafo(_contato(p), 9.5)
    pdf.secao(t["resumo"])
    pdf.paragrafo(d["resumo"])
    pdf.secao(t["competencias"])
    pdf.paragrafo(" | ".join(d["competencias"]))
    pdf.secao(t["experiencia"])
    for e in d["experiencias"]:
        pdf.ln(1)
        pdf.paragrafo(f"{e['cargo']}, {e['empresa']}", 10.5, "B")
        pdf.paragrafo(" | ".join(x for x in (e.get("local"), e["periodo"]) if x), 9.5, "I")
        for b in e["bullets"]:
            pdf.bullet(b)
    pdf.secao(t["formacao"])
    for f in d["formacao"]:
        pdf.paragrafo(", ".join(x for x in (f["curso"], f["instituicao"], f.get("periodo")) if x))
    if d.get("certificacoes"):
        pdf.secao(t["certificacoes"])
        for c in d["certificacoes"]:
            pdf.bullet(c)
    if d.get("ferramentas"):
        pdf.secao(t["ferramentas"])
        pdf.paragrafo(", ".join(d["ferramentas"]))
    pdf.secao(t["idiomas"])
    pdf.paragrafo(" | ".join(d["idiomas"]))
    pdf.output(str(destino))


# ------------------------------------------------------------------ DOCX
def _docx(d: dict, p: dict, idioma: str, destino: Path) -> None:
    t = TITULOS.get(idioma, TITULOS["pt"])
    doc = Document()
    for s in doc.sections:
        s.left_margin = s.right_margin = Pt(51)
        s.top_margin = s.bottom_margin = Pt(42)
    base = doc.styles["Normal"]
    base.font.name, base.font.size = "Arial", Pt(10)

    def par(texto, tam=10, negrito=False, italico=False, depois=2):
        para = doc.add_paragraph()
        r = para.add_run(_limpar(texto))
        r.bold, r.italic, r.font.size = negrito, italico, Pt(tam)
        para.paragraph_format.space_after = Pt(depois)
        return para

    def secao(titulo):
        para = par(titulo, 11, True, depois=3)
        para.paragraph_format.space_before = Pt(8)
        para.runs[0].font.color.rgb = RGBColor(20, 20, 20)

    par(p.get("nome_completo", ""), 17, True, depois=0)
    par(d["titulo_profissional"], 11, True, depois=0)
    par(_contato(p), 9.5)
    secao(t["resumo"]); par(d["resumo"])
    secao(t["competencias"]); par(" | ".join(d["competencias"]))
    secao(t["experiencia"])
    for e in d["experiencias"]:
        par(f"{e['cargo']}, {e['empresa']}", 10.5, True, depois=0)
        par(" | ".join(x for x in (e.get("local"), e["periodo"]) if x), 9.5, italico=True)
        for b in e["bullets"]:
            doc.add_paragraph(_limpar(b), style="List Bullet").paragraph_format.space_after = Pt(1)
    secao(t["formacao"])
    for f in d["formacao"]:
        par(", ".join(x for x in (f["curso"], f["instituicao"], f.get("periodo")) if x))
    if d.get("certificacoes"):
        secao(t["certificacoes"])
        for c in d["certificacoes"]:
            doc.add_paragraph(_limpar(c), style="List Bullet")
    if d.get("ferramentas"):
        secao(t["ferramentas"]); par(", ".join(d["ferramentas"]))
    secao(t["idiomas"]); par(" | ".join(d["idiomas"]))
    for para in doc.paragraphs:
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    doc.core_properties.author = p.get("nome_completo", "")
    doc.save(str(destino))


def gerar_arquivos(vaga: dict, dados: dict, p: dict, pasta: Path | None = None) -> tuple[Path, Path, Path]:
    idioma = vaga.get("idioma") or "pt"
    t = TITULOS.get(idioma, TITULOS["pt"])
    if pasta is None:
        slug = normalizar(f"{vaga.get('empresa', '')} {vaga['titulo']}").replace(" ", "-")[:70]
        pasta = SAIDA / f"{date.today().isoformat()}_{slug}"
    pasta.mkdir(parents=True, exist_ok=True)
    nome = normalizar(p.get("nome_completo") or "Candidato").title().replace(" ", "_")
    pdf, docx = pasta / f"{nome}_{t['arquivo']}.pdf", pasta / f"{nome}_{t['arquivo']}.docx"
    _pdf(dados, p, idioma, pdf)
    _docx(dados, p, idioma, docx)
    js = pdf.with_suffix(".json")
    js.write_text(json.dumps({**dados, "vaga_id": vaga.get("id"), "idioma": idioma}, ensure_ascii=False, indent=2),
                  encoding="utf-8")
    (pasta / "carta.txt").write_text(dados.get("carta", ""), encoding="utf-8")
    return pdf, docx, js

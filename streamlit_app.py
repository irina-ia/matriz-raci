# streamlit_app.py — versión robusta para despliegue en Streamlit Cloud
# - Busca el Excel en rutas típicas (evita errores por espacios/acentos)
# - Soporta carga por file_uploader si el archivo no está en el repo
# - Selección de hoja inteligente (usa "streamlit" o la primera disponible)
# - Contadores abajo y descarga XLSX con nombre yyyyMMDD_proceso_area.xlsx

from __future__ import annotations
import re
import base64
import unicodedata
from io import BytesIO
from datetime import datetime
from mimetypes import guess_type
from pathlib import Path
from typing import Tuple

import pandas as pd
import streamlit as st

# --- Optional: use AG Grid if available (mobile-friendly table) ---
try:
    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode, GridUpdateMode
    AGGRID_AVAILABLE = True
except Exception:
    AGGRID_AVAILABLE = False

# -------------------- Configuración general --------------------

def _find_logo_path():
    candidates = [
        Path("logo_2024.svg"), Path("logo_2024.png"), Path("logo_2024.jpg"), Path("logo_2024"),
        Path("Metro Santiago.jpg"), Path("Metro Santiago.JPG"), Path("logo_metro_versiones-05.jpg"),
        Path("assets/metro_logo.png"), Path("assets/metro_logo.jpg")
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None

_page_icon = _find_logo_path()
st.set_page_config(page_title="Matriz RACI", page_icon=_page_icon or "🅼", layout="wide")

COLOR_PRIMARIO = "#E10600"  # rojo Metro
COLOR_BORDE = "#e5e7eb"
COLOR_TXT_SUAVE = "#6b7280"

# -------------------- Estilos --------------------
st.markdown(
    f"""
<style>
  .block-container {{ padding-top: 92px; padding-bottom: 1rem; }}
  h1, h2, h3, h4 {{ font-weight: 800; letter-spacing: .2px; }}

  /* TOP BAR */
  .metro-topbar {{ position: sticky; top: 0; z-index: 1000; background: linear-gradient(90deg, #E10600 0%, #C20A0A 50%, #9E0B0B 100%); color: #fff; border-bottom: 1px solid #9e0b0b; box-shadow: 0 4px 10px rgba(0,0,0,.18); }}
  .metro-topbar .wrap {{ max-width: 1200px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; padding: 8px 20px; }}
  .metro-topbar .brand {{ display:flex; align-items:center; gap:.6rem; }}
  .metro-topbar .brand img {{ height: 28px; }}
  .metro-topbar .name {{ font-weight:800; letter-spacing:.3px; }}
  .matriz-title {{ display:inline-block; font-weight:800; letter-spacing:.3px; border:1px solid rgba(255,255,255,.45); background: rgba(255,255,255,.16); padding: 8px 16px; border-radius: 999px; box-shadow: inset 0 0 0 1px rgba(255,255,255,.08); }}

  /* Chips y métricas */
  .metro-chip {{ display:inline-flex; align-items:center; gap:.5rem; font-weight:700; border:1px solid {COLOR_BORDE}; border-radius:999px; padding:.35rem .8rem; background:#fff; box-shadow: 0 1px 2px rgba(0,0,0,.04); }}
  .dot {{ width:.75rem; height:.75rem; border-radius:50%; display:inline-block; }}
  .A {{ background:#ef4444; }}
  .R {{ background:#10b981; }}
  .C {{ background:#f59e0b; }}
  .I {{ background:#3b82f6; }}
  .AR {{ background:linear-gradient(90deg,#ef4444,#10b981); }}

  .metric {{ border:1px solid {COLOR_BORDE}; border-radius:16px; padding:12px 14px; background:#fff; text-align:center; }}
  .metric .num {{ font-size:1.6rem; font-weight:900; }}
  .metric .lbl {{ color:{COLOR_TXT_SUAVE}; font-weight:600; letter-spacing:.5px; white-space: nowrap; }}; font-weight:600; letter-spacing:.5px; }}

  .stDataFrame {{ border:1px solid {COLOR_BORDE}; border-radius: 12px; }}

  /* AG Grid theme tweaks */
  .ag-theme-alpine {{
    --ag-header-background-color: #fafafa;
    --ag-odd-row-background-color: #ffffff;
    --ag-row-border-color: {COLOR_BORDE};
    --ag-header-foreground-color: #111827;
    --ag-selected-row-background-color: #fff7ed;
    --ag-font-size: 14px;
    border: 1px solid {COLOR_BORDE};
    border-radius: 12px;
  }}
  .ag-theme-alpine .ag-cell-wrap-text {{ white-space: normal !important; }}
  .ag-theme-alpine .ag-header-cell-label {{ justify-content: center; }}
  .ag-theme-alpine .ag-header-cell-text {{ text-align: center; width: 100%; }}

  @media (max-width: 640px) {{
    .block-container {{ padding-left: 10px; padding-right: 10px; padding-top: 80px; }}
    .metro-topbar .wrap {{ padding: 6px 12px; }}
  }}
</style>
""",
    unsafe_allow_html=True,
)

# -------------------- Top bar con logo --------------------

def _logo_data_url() -> str:
    # Logo visible dentro de la página (topbar)
    return "https://i.pinimg.com/736x/46/6a/3a/466a3af75320ca9bb837c5c7bff3326b.jpg"

_logo = _logo_data_url()
_logo_tag = f"<img src='{_logo}' alt='Metro'/>" if _logo else ""

st.markdown(
    f"""
<div class='metro-topbar'>
  <div class='wrap'>
    <div class='brand'>
      {_logo_tag}
      <span class='name'>Metro de Santiago</span>
    </div>
    <span class='matriz-title'>Matriz RACI</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# -------------------- Carga de datos (robusta) --------------------
BASE_DIR = Path(__file__).resolve().parent
PREFERRED_SHEET = "streamlit"  # ajusta si aplica


def _find_excel_candidates() -> list[Path]:
    pats = [
        BASE_DIR / "data",
        BASE_DIR,
    ]
    found: list[Path] = []
    for root in pats:
        if root.exists():
            found += list(root.glob("**/*[Mm]atriz*[Rr][Aa][Cc][Ii]*.xlsx"))
            found += list(root.glob("**/*raci*.xlsx"))
    # Evitar duplicados conservando orden
    uniq = []
    seen = set()
    for p in found:
        if p.resolve() not in seen:
            uniq.append(p)
            seen.add(p.resolve())
    return uniq


@st.cache_data
def _load_from_path(path: str | Path, preferred_sheet: str) -> Tuple[pd.DataFrame, str]:
    path = Path(path)
    xls = pd.ExcelFile(path)
    sheet = preferred_sheet if preferred_sheet in xls.sheet_names else xls.sheet_names[0]
    df = pd.read_excel(path, sheet_name=sheet)
    df.columns = df.columns.str.strip()
    return df, sheet


@st.cache_data
def _load_from_bytes(data: bytes, preferred_sheet: str) -> Tuple[pd.DataFrame, str]:
    bio = BytesIO(data)
    xls = pd.ExcelFile(bio)
    sheet = preferred_sheet if preferred_sheet in xls.sheet_names else xls.sheet_names[0]
    bio.seek(0)
    df = pd.read_excel(bio, sheet_name=sheet)
    df.columns = df.columns.str.strip()
    return df, sheet


with st.sidebar:
    st.header("Origen de datos")
    uploaded = st.file_uploader("Sube Excel RACI (.xlsx)", type=["xlsx"], help="Si no subes nada, la app buscará un archivo en el repo (data/ o raíz)")

# Resolver origen de datos
if uploaded is not None:
    df, SHEET_USED = _load_from_bytes(uploaded.getvalue(), PREFERRED_SHEET)
    DATA_SOURCE = f"archivo subido: {uploaded.name}"
else:
    candidates = _find_excel_candidates()
    if not candidates:
        st.error(
            "No encuentro el Excel RACI. Sube un archivo con el botón de la barra lateral "
            "o agrega uno al repo (sugerido: data/Matriz_RACI_Nico.xlsx)."
        )
        st.stop()
    # usa el primero
    path = candidates[0]
    df, SHEET_USED = _load_from_path(path, PREFERRED_SHEET)
    DATA_SOURCE = f"repo: {path.relative_to(BASE_DIR)}"

st.markdown("---")
# st.caption(f"Origen: {DATA_SOURCE} — Hoja: {SHEET_USED}")

# -------------------- Descubrimiento de columnas RACI --------------------
BASE_COLS = [c for c in ["Proceso", "Tarea"] if c in df.columns]
RACI_PAT = re.compile(r"^[ARCI/\-\s,]*$")
_cands = [c for c in df.columns if c not in BASE_COLS]
area_cols = [
    c for c in _cands
    if ({str(v).strip().upper() for v in df[c].dropna().unique()} and
        all(RACI_PAT.match(str(v).strip().upper() or "") for v in df[c].dropna().unique()))
] or _cands

# -------------------- Sidebar filtros --------------------
with st.sidebar:
    st.header("Filtros")
    default_area_name = "Cultura Organizacional"
    default_areas = [a for a in area_cols if a == default_area_name] or (area_cols[:1] if area_cols else [])
    areas_sel = st.multiselect("Áreas (columnas)", area_cols, default=default_areas)
    roles_all = ["A", "R", "C", "I"]
    roles_sel = st.multiselect("Rol RACI", roles_all, default=roles_all)
    q = st.text_input("Buscar en Proceso/Tarea", placeholder="Palabra clave…")

    

    # Filtro Proceso (desde df completo para que siempre estén todas las opciones)
    proc_sel = None
    if 'Proceso' in df.columns:
        proc_series_full = df['Proceso'].dropna().astype(str).str.strip()
        proc_options = list(pd.unique(proc_series_full))
        preferred_proc = "Definición de Metas"
        initial_default = [p for p in proc_options if p == preferred_proc] or (proc_options[:1] if proc_options else [])
        # if 'proc_sel_multi' not in st.session_state:
        #     st.session_state['proc_sel_multi'] = initial_default
        proc_sel = st.multiselect('Proceso', proc_options, default=st.session_state['proc_sel_multi'], key='proc_sel_multi', help='Puedes seleccionar uno o varios procesos')

# -------------------- Lógica de filtrado --------------------
ROLE_RE = re.compile(r"[ARCI]")


def parse_roles(cell: str) -> set[str]:
    if cell is None:
        return set()
    return set(ROLE_RE.findall(str(cell).upper()))


# Construcción del dataframe de trabajo (múltiples áreas)
id_cols = [c for c in ["Proceso", "Tarea"] if c in df.columns]
areas_to_use = areas_sel if areas_sel else area_cols
work = df.melt(id_vars=id_cols, value_vars=areas_to_use, var_name="Área", value_name="Rol")

# Normaliza
work["Rol"] = work["Rol"].fillna("").astype(str).str.upper().str.replace(" ", "", regex=False)

# Filtrar por roles
if roles_sel:
    sel = set(roles_sel)
    mask_roles = work["Rol"].apply(lambda x: bool(parse_roles(x)) and parse_roles(x).issubset(sel))
    work = work[mask_roles]
else:
    work = work.iloc[0:0]

# Filtrar por proceso (si aplica)
if proc_sel and 'Proceso' in work.columns:
    work = work[work['Proceso'].astype(str).str.strip().isin(proc_sel)]

# Filtro de búsqueda
if q:
    cols = [c for c in ["Proceso", "Tarea"] if c in work.columns]
    if cols:
        m = False
        for c in cols:
            m = m | work[c].astype(str).str.contains(q, case=False, na=False)
        work = work[m]

# -------------------- Cálculo de métricas --------------------
count_A  = int(work["Rol"].apply(lambda x: "A" in parse_roles(x)).sum())
count_R  = int(work["Rol"].apply(lambda x: "R" in parse_roles(x)).sum())
count_C  = int(work["Rol"].apply(lambda x: "C" in parse_roles(x)).sum())
count_I  = int(work["Rol"].apply(lambda x: "I" in parse_roles(x)).sum())
count_AR = int(work["Rol"].apply(lambda x: parse_roles(x) == {"A","R"}).sum())

# -------------------- CONTADORES (movidos ABAJO) --------------------
col1, col2, col3, col4, col5 = st.columns([1,1,1,1,1])
col1.markdown(f"""
<div class='metric'>
  <div class='lbl'><span class='dot A'></span> A (Accountable)</div>
  <div class='num'>{count_A}</div>
</div>""", unsafe_allow_html=True)
col2.markdown(f"""
<div class='metric'>
  <div class='lbl'><span class='dot R'></span> R (Responsible)</div>
  <div class='num'>{count_R}</div>
</div>""", unsafe_allow_html=True)
col3.markdown(f"""
<div class='metric'>
  <div class='lbl'><span class='dot C'></span> C (Consulted)</div>
  <div class='num'>{count_C}</div>
</div>""", unsafe_allow_html=True)
col4.markdown(f"""
<div class='metric'>
  <div class='lbl'><span class='dot I'></span> I (Informed)</div>
  <div class='num'>{count_I}</div>
</div>""", unsafe_allow_html=True)
if {"A","R"}.issubset(set(roles_sel)):
    col5.markdown(f"""
    <div class='metric'>
      <div class='lbl'><span class='dot AR'></span> A/R (Accountable&nbsp;&amp;&nbsp;Responsible)</div>
      <div class='num'>{count_AR}</div>
    </div>""", unsafe_allow_html=True)
else:
    col5.empty()

# -------------------- Tabla --------------------
area_title = areas_to_use[0] if len(areas_to_use) == 1 else f"{len(areas_to_use)} áreas"
st.subheader(f"Tareas para **{area_title}**")
if proc_sel:
    if isinstance(proc_sel, list) and len(proc_sel) > 1:
        shown = ", ".join(proc_sel[:4]) + ("…" if len(proc_sel) > 4 else "")
        st.caption(f"Procesos seleccionados: {shown}")
    elif isinstance(proc_sel, list) and len(proc_sel) == 1:
        st.caption(f"Proceso seleccionado: {proc_sel[0]}")

multi_proc = ('Proceso' in work.columns) and proc_sel and len(proc_sel) > 1
view_cols = ['Tarea']
if multi_proc:
    view_cols.append('Proceso')
view_cols += ['Área', 'Rol']
view = work.loc[:, [c for c in view_cols if c in work.columns]].rename(columns={'Rol': 'Rol (RACI)'})
# Oculta columna Área cuando sólo hay una seleccionada
if 'Área' in view.columns and len(areas_to_use) == 1:
    view = view.drop(columns=['Área'])

# Ordenar alfabéticamente por Tarea (ignorando tildes y mayúsculas)

def _sort_key_series(s: pd.Series) -> pd.Series:
    return s.astype(str).map(lambda x: ''.join(c for c in unicodedata.normalize('NFD', x) if unicodedata.category(c) != 'Mn').lower())


if 'Tarea' in view.columns:
    sort_by = []
    if 'Proceso' in view.columns:
        sort_by.append('Proceso')
    if 'Área' in view.columns:
        sort_by.append('Área')
    sort_by.append('Tarea')
    view = view.sort_values(by=sort_by, key=_sort_key_series, kind='mergesort').reset_index(drop=True)

# Agrega columna de IDs 1..N (después del ordenamiento)
# Elimina cualquier columna ID previa (del Excel) y crea una nueva 1..N
if 'ID' in view.columns:
    view = view.drop(columns=['ID'])
view.insert(0, 'ID', range(1, len(view) + 1))
# fuerza tipo numérico para evitar orden lexicográfico en AgGrid
view['ID'] = pd.to_numeric(view['ID'], errors='coerce').fillna(0).astype(int)
# Asegura orden por ID ascendente por defecto
view = view.sort_values(by='ID', kind='mergesort').reset_index(drop=True)

# --- Tabla con AG Grid (responsive y mobile-friendly) ---
# Orden final: ID | Rol | Tarea | (Área) | (Proceso)
col_order = [c for c in ['ID', 'Rol (RACI)', 'Tarea', 'Área', 'Proceso'] if c in view.columns]
view = view[col_order]

if AGGRID_AVAILABLE:
    gb = GridOptionsBuilder.from_dataframe(view)
    gb.configure_default_column(resizable=True, sortable=True, filter=True, wrapText=True, autoHeight=True)
    gb.configure_grid_options(domLayout='normal', quickFilterText=(q or ""), rowHeight=36, headerHeight=38, suppressPaginationPanel=True)

    # Columna ID (fijada izquierda)
    if 'ID' in view.columns:
        id_num_sort = JsCode("function(a,b){ return Number(a) - Number(b); }")
        gb.configure_column(
            'ID', header_name='ID', width=70, minWidth=60, maxWidth=80,
            pinned='left', sort='asc', type=['numericColumn','numberColumnFilter'], comparator=id_num_sort
        )

    # Columna Rol (protagónica y SIEMPRE visible)
    if 'Rol (RACI)' in view.columns:
        raci_renderer = JsCode("""
class RaciRenderer {
  init(params){
    const val = (params.value || '').toString().toUpperCase().split(' ').join('');
    const map = { 'A':'#ef4444','R':'#10b981','C':'#f59e0b','I':'#3b82f6' };
    const dot = function(c){
      return '<span style=\"display:inline-block;width:10px;height:10px;border-radius:50%;background:'+c+';margin-right:6px;\"></span>';
    };
    let html;
    if (val==='A/R' || val==='AR' || val==='A,R'){
      html = dot('#ef4444') + dot('#10b981') + 'A/R';
    } else {
      const color = map[val] || '#9ca3af';
      html = dot(color) + val;
    }
    this.eGui = document.createElement('span');
    this.eGui.style.whiteSpace = 'nowrap';
    this.eGui.style.fontWeight = '700';
    this.eGui.innerHTML = html;
  }
  getGui(){ return this.eGui; }
}
""")
        gb.configure_column(
            'Rol (RACI)', header_name='Rol', pinned='right', width=170, minWidth=150, maxWidth=230,
            cellRenderer=raci_renderer, wrapText=False, autoHeight=True,
            cellStyle={'white-space':'nowrap','text-align':'center','font-weight':'700'}
        )

    # Tarea y otras columnas
    if 'Tarea' in view.columns:
        gb.configure_column('Tarea', header_name='Tarea', flex=3, minWidth=260, cellStyle={'white-space':'normal'})
    if 'Área' in view.columns:
        gb.configure_column('Área', header_name='Área', flex=2, minWidth=160)
    if 'Proceso' in view.columns:
        gb.configure_column('Proceso', header_name='Proceso', flex=2, minWidth=160)

    # Override para fijar Rol a la izquierda y centrar
    try:
        gb.configure_column('Rol (RACI)', header_name='Rol', pinned='left', width=170, minWidth=150, maxWidth=230,
                            cellRenderer=raci_renderer, wrapText=False, autoHeight=True,
                            cellStyle={'white-space':'nowrap','text-align':'center','font-weight':'700'})
    except Exception:
        pass
    go = gb.build()
    AgGrid(
        view,
        height=420,
        gridOptions=go,
        theme='alpine',
        fit_columns_on_grid_load=True,
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        update_mode=GridUpdateMode.NO_UPDATE,
    )
else:
    # Fallback sin AgGrid: orden ID | Rol | Tarea | (Área) | (Proceso)
    view_disp = view.copy()
    col_order = [c for c in ['ID', 'Rol (RACI)', 'Tarea', 'Área', 'Proceso'] if c in view_disp.columns]
    view_disp = view_disp[col_order]

    def raci_emoji(v: str) -> str:
        val = str(v or "").upper().replace(" ", "")
        if val in ("A", "R", "C", "I"):
            return {"A": "🔴 A", "R": "🟢 R", "C": "🟠 C", "I": "🔵 I"}[val]
        if val in ("AR", "A/R", "A,R"):
            return "🔴🟢 A/R"
        return str(v)

    if 'Rol (RACI)' in view_disp.columns:
        view_disp['Rol (RACI)'] = view_disp['Rol (RACI)'].map(raci_emoji)

        def raci_style(s: pd.Series):
            styles = []
            for v in s.astype(str):
                # Sin relleno de color: solo énfasis tipográfico y no wrap
                styles.append('font-weight:700; white-space:nowrap;')
            return styles

        sty = (
            view_disp.style
            .apply(raci_style, subset=['Rol (RACI)'])
            .set_properties(subset=['Rol (RACI)'], **{'text-align':'center'})
            .set_properties(subset=['ID'], **{'text-align':'center','width':'56px'})
        )
        sty = sty.set_table_styles([
            {'selector': 'th', 'props': 'text-align: center;'},
            {'selector': '.col0', 'props': 'min-width:56px; width:56px; text-align:center;'}
        ], overwrite=False)
        st.dataframe(sty, use_container_width=True, hide_index=True)
    else:
        st.dataframe(view_disp, use_container_width=True, hide_index=True)

# # -------------------- CONTADORES (movidos ABAJO) --------------------
# col1, col2, col3, col4, col5 = st.columns([1,1,1,1,1])
# col1.markdown(f"""
# <div class='metric'>
#   <div class='lbl'><span class='dot A'></span> A (Accountable)</div>
#   <div class='num'>{count_A}</div>
# </div>""", unsafe_allow_html=True)
# col2.markdown(f"""
# <div class='metric'>
#   <div class='lbl'><span class='dot R'></span> R (Responsible)</div>
#   <div class='num'>{count_R}</div>
# </div>""", unsafe_allow_html=True)
# col3.markdown(f"""
# <div class='metric'>
#   <div class='lbl'><span class='dot C'></span> C (Consulted)</div>
#   <div class='num'>{count_C}</div>
# </div>""", unsafe_allow_html=True)
# col4.markdown(f"""
# <div class='metric'>
#   <div class='lbl'><span class='dot I'></span> I (Informed)</div>
#   <div class='num'>{count_I}</div>
# </div>""", unsafe_allow_html=True)
# if {"A","R"}.issubset(set(roles_sel)):
#     col5.markdown(f"""
#     <div class='metric'>
#       <div class='lbl'><span class='dot AR'></span> A/R (Accountable&nbsp;&amp;&nbsp;Responsible)</div>
#       <div class='num'>{count_AR}</div>
#     </div>""", unsafe_allow_html=True)
# else:
#     col5.empty()

# -------------------- Descarga XLSX (al final) --------------------

def _slugify(text: str) -> str:
    norm = ''.join(c for c in unicodedata.normalize('NFD', str(text)) if unicodedata.category(c) != 'Mn')
    norm = norm.lower().strip()
    norm = re.sub(r"[^a-z0-9]+", "_", norm)
    norm = re.sub(r"_+", "_", norm).strip('_')
    return norm or 'sin_nombre'

def _short_join(parts: list[str], limit: int = 3) -> str:
    s = "_".join(parts[:limit])
    return s + ("_etc" if len(parts) > limit else "")

# Nombre de archivo en base a selección
areas_for_name = (
    "todas_las_areas" if len(areas_to_use) == len(area_cols)
    else _short_join([_slugify(a) for a in areas_to_use]) or "todas_las_areas"
)

if 'Proceso' in df.columns:
    total_procs = df['Proceso'].dropna().astype(str).str.strip().nunique()
else:
    total_procs = 0

if proc_sel and total_procs and len(proc_sel) < total_procs:
    procs_for_name = _short_join([_slugify(p) for p in proc_sel])
else:
    procs_for_name = 'todos_los_procesos'

filename = f"{datetime.now():%Y%m%d}_{procs_for_name}_{areas_for_name}.xlsx"

bio = BytesIO()
with pd.ExcelWriter(bio, engine='openpyxl') as writer:
    view.to_excel(writer, index=False, sheet_name='raci')
bio.seek(0)

st.markdown("---")

st.download_button(
    label="Descargar XLSX",
    data=bio,
    file_name=filename,
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
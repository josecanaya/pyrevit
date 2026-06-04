# -*- coding: utf-8 -*-
"""
Cruce diagnostico Project/Revit generico por planta.

No usa Revit API y no escribe nada en Revit. Reutiliza la logica probada en
preparar_match_project_revit_p10.py, parametrizando codigo de planta, entradas
y carpeta de salida.
"""
from __future__ import print_function

import argparse
import codecs
import csv
import json
import os
import re
import shutil
import sys

import preparar_match_project_revit_p10 as core


EXT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), u"..", u".."))
PUBLIC_DIR = os.path.join(EXT_DIR, u"public")
INPUT_DIR = os.path.join(PUBLIC_DIR, u"input")
CONSOLE_DIR = os.path.join(EXT_DIR, u"btz_console")
if CONSOLE_DIR not in sys.path:
    sys.path.insert(0, CONSOLE_DIR)
from project_parser import discover_project_xmls, infer_plant_from_project  # noqa: E402

PROJECT_DIR = os.path.join(PUBLIC_DIR, u"project")
DEFAULT_CONFIG = os.path.join(PROJECT_DIR, u"projects_config.json")
PLANTAS_DEFAULT = (u"P10", u"PP", u"TE", u"PR")


try:
    unicode
except NameError:
    unicode = str


def _u(value):
    if value is None:
        return u""
    try:
        return unicode(value).strip()
    except Exception:
        try:
            return unicode(str(value)).strip()
        except Exception:
            return u""


def _abs_path(path):
    path = _u(path)
    if not path:
        return u""
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(EXT_DIR, path))


def _load_config(path):
    if not path:
        return {}
    if not os.path.isfile(path):
        return {}
    with codecs.open(path, u"r", encoding=u"utf-8-sig") as fp:
        raw = fp.read()
    return json.loads(raw)


def _default_revit_export(planta):
    return os.path.join(PUBLIC_DIR, u"modelo_btz_export_{0}.csv".format(_u(planta).lower()))


def _default_output_dir(planta):
    return os.path.join(PUBLIC_DIR, u"output", _u(planta).upper())


def _find_project_for_plant(planta):
    plant = _u(planta).upper()
    candidates = []
    for item in discover_project_xmls(PROJECT_DIR):
        if item.get(u"planta") == plant:
            candidates.append(item.get(u"path"))
    if candidates:
        return candidates[0]
    raise IOError(u"No se encontró XML compatible con {0} en {1}".format(plant, PROJECT_DIR))


def _resolve_project_xml_for_plant(planta, config_project, cli_project):
    plant = _u(planta).upper()
    tried_cli = _abs_path(cli_project)
    if _u(config_project):
        pcfg = _abs_path(config_project)
        if pcfg and os.path.isfile(pcfg):
            return pcfg
    if tried_cli:
        if os.path.isfile(tried_cli):
            return tried_cli
        raise IOError(
            u"No se encontró el Project XML para {0} en la ruta indicada:\n{1}".format(plant, tried_cli)
        )
    input_xml = os.path.join(PUBLIC_DIR, u"input", u"{0}.xml".format(plant))
    if os.path.isfile(input_xml):
        return input_xml
    try:
        return _find_project_for_plant(planta)
    except IOError:
        raise IOError(
            u"No se encontró el Project XML para {0}. Indicar --project o colocar el archivo en public/input/{0}.xml.".format(
                plant
            )
        )


def _discover_entries_from_project_dir():
    entries = []
    for item in discover_project_xmls(PROJECT_DIR):
        plant = item.get(u"planta") or infer_plant_from_project(item.get(u"path"))
        if plant not in PLANTAS_DEFAULT:
            continue
        entries.append((plant, item.get(u"path"), _default_revit_export(plant), _default_output_dir(plant)))
    if not entries:
        raise IOError(u"No se detectaron Project XML P10/PP/TE/PR en {0}".format(PROJECT_DIR))
    return entries


def _configure_core_for_plant(planta):
    plant = _u(planta).upper()
    core.PLANT_CODE = plant
    core.PROJECT_CODE_RE = re.compile(r"^({0}-[^\s,;|]+)".format(re.escape(plant)), re.IGNORECASE)
    core.ANY_P10_CODE_RE = re.compile(
        r"(?<![A-Z0-9]){0}-[A-Z0-9][A-Z0-9_.\-/]*".format(re.escape(plant)),
        re.IGNORECASE,
    )


def _paths_for_output_dir(output_dir, planta):
    pl = _u(planta).lower()
    return {
        u"out": os.path.join(output_dir, u"match_project_revit_preparacion.csv"),
        u"summary": os.path.join(output_dir, u"match_project_revit_preparacion_summary.txt"),
        u"containers": os.path.join(output_dir, u"contenedores_revit.csv"),
        u"confirmado_auto": os.path.join(output_dir, u"match_project_revit_confirmado_auto.csv"),
        u"revision": os.path.join(output_dir, u"match_project_revit_revision.csv"),
        u"container_children": os.path.join(output_dir, u"asociacion_contenedor_hijos.csv"),
        u"apply_ready": os.path.join(output_dir, u"match_project_revit_confirmado_para_aplicar.csv"),
        u"apply": os.path.join(output_dir, u"match_project_revit_confirmado.csv"),
        u"container_children_final": os.path.join(
            output_dir, u"asociacion_contenedor_hijos_final_{0}.csv".format(pl)
        ),
        u"container_children_omitted": os.path.join(
            output_dir,
            u"asociacion_contenedor_hijos_final_{0}_omitidos_por_slots.csv".format(pl),
        ),
        u"apply_summary": os.path.join(output_dir, u"preparar_aplicacion_btz_summary.txt"),
        u"general_fallback_csv": os.path.join(output_dir, u"faltantes_reclasificados_por_general.csv"),
        u"general_fallback_summary": os.path.join(
            output_dir, u"faltantes_reclasificados_por_general_summary.txt"
        ),
        u"faltantes_modelo": os.path.join(output_dir, u"project_codigos_faltantes_en_modelo.csv"),
    }


def _write_project_codigos_faltantes_csv(path, out_rows):
    fields = [
        u"codigo_project",
        u"task_name",
        u"estado_match",
        u"observacion",
        u"tipo_asociacion",
    ]
    rows_out = []
    for r in out_rows:
        if _u(r.get(u"estado_match")) != u"sin_contenedor":
            continue
        rows_out.append({k: _u(r.get(k)) for k in fields})
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with codecs.open(path, u"w", encoding=u"utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=fields, lineterminator=u"\n")
        w.writeheader()
        for row in rows_out:
            w.writerow(row)


def run_plant(
    planta,
    project_path,
    revit_path,
    output_dir,
    copy_to_public=False,
    cluster_mode=None,
    force_ancestor_container=None,
):
    plant = _u(planta).upper()
    _configure_core_for_plant(plant)

    core.EXTENDED_CLUSTER_STATES = plant in (u"TE", u"PP")
    if core.EXTENDED_CLUSTER_STATES:
        core.CLUSTER_MODE = _u(cluster_mode).lower() if cluster_mode else u"distributed"
    else:
        core.CLUSTER_MODE = u"distributed"

    if force_ancestor_container is None:
        core.FORCE_ANCESTOR_CONTAINER = plant in (u"TE", u"PP")
    else:
        core.FORCE_ANCESTOR_CONTAINER = bool(force_ancestor_container)

    project_path = core.resolve_project_path(_abs_path(project_path))
    revit_path = _abs_path(revit_path)
    output_dir = _abs_path(output_dir)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    paths = _paths_for_output_dir(output_dir, plant)
    if not os.path.isfile(revit_path):
        raise IOError(
            u"No se encontró el CSV exportado del modelo Revit para {0}:\n{1}\n"
            u"Exportá desde Revit (modelo_btz_export_{2}.csv) o usá --revit.".format(
                plant, revit_path, plant.lower()
            )
        )

    project_items, project_meta = core.load_project_codes(project_path)
    revit_rows, revit_meta = core.load_revit_rows(revit_path)
    containers = core.build_revit_containers(revit_rows)
    project_meta[u"path"] = project_path
    revit_meta[u"path"] = revit_path

    out_rows, counts = core.compare(project_items, revit_rows, containers)
    _write_project_codigos_faltantes_csv(paths[u"faltantes_modelo"], out_rows)
    core.write_csv(paths[u"out"], out_rows)
    core.write_containers_csv(paths[u"containers"], containers)
    post_counts = core.write_postprocess_outputs(
        out_rows,
        paths[u"confirmado_auto"],
        paths[u"revision"],
        paths[u"container_children"],
    )
    apply_counts = core.prepare_apply_confirmed_outputs(
        out_rows,
        containers,
        paths[u"apply_ready"],
        paths[u"apply"],
        paths[u"container_children_final"],
        paths[u"container_children_omitted"],
        paths[u"apply_summary"],
    )
    core.write_summary(
        paths[u"summary"],
        project_items,
        revit_rows,
        containers,
        counts,
        project_meta,
        revit_meta,
        paths[u"out"],
        paths[u"containers"],
        post_counts,
        out_rows,
        apply_counts,
    )
    core.write_general_fallback_reports(
        out_rows,
        revit_rows,
        paths[u"general_fallback_csv"],
        paths[u"general_fallback_summary"],
    )
    with codecs.open(paths[u"summary"], u"a", encoding=u"utf-8") as fp:
        ya_en_modelo = (
            int(counts.get(u"match_elemento_puntual", 0) or 0)
            + int(counts.get(u"asignable_a_contenedor", 0) or 0)
        )
        listos = int(post_counts.get(u"total_confirmado_auto", 0) or 0) + int(
            post_counts.get(u"total_revision", 0) or 0
        )
        fp.write(
            u"\n---\nPlanta: {4}\n"
            u"project_codigos_ya_en_modelo_puntual_o_contenedor: {0}\n"
            u"match_directo_elemento_puntual: {1}\n"
            u"match_por_contenedor_ancestro: {2}\n"
            u"sin_contenedor: {5}\n"
            u"duplicado: {6}\n"
            u"contenedor_duplicado: {7}\n"
            u"total_confirmado_auto: {12}\n"
            u"total_para_revision_humana: {13}\n"
            u"total_filas_post_csvs_auto_y_revision: {3}\n"
            u"hijos_omitidos_por_slots: {8}\n"
            u"project_codigos_faltantes_en_modelo.csv: {9}\n"
            u"asociacion_contenedor_hijos_final: {10}\n"
            u"omitidos_por_slots_csv: {11}\n".format(
                ya_en_modelo,
                counts.get(u"match_elemento_puntual", 0),
                counts.get(u"asignable_a_contenedor", 0),
                listos,
                plant,
                counts.get(u"sin_contenedor", 0),
                counts.get(u"duplicado", 0),
                counts.get(u"contenedor_duplicado", 0),
                apply_counts.get(u"total_hijos_omitidos_por_slots", 0),
                paths[u"faltantes_modelo"],
                paths[u"container_children_final"],
                paths[u"container_children_omitted"],
                post_counts.get(u"total_confirmado_auto", 0),
                post_counts.get(u"total_revision", 0),
            )
        )

    copied_public = u""
    if copy_to_public:
        copied_public = os.path.join(PUBLIC_DIR, u"match_project_revit_confirmado.csv")
        shutil.copyfile(paths[u"apply"], copied_public)

    return {
        u"planta": plant,
        u"project": project_path,
        u"revit": revit_path,
        u"output_dir": output_dir,
        u"paths": paths,
        u"copied_public": copied_public,
        u"project_count": len(project_items),
        u"revit_count": len(revit_rows),
        u"container_count": len(containers),
        u"counts": counts,
        u"post_counts": post_counts,
        u"apply_counts": apply_counts,
        u"general_fallback_csv": paths[u"general_fallback_csv"],
        u"general_fallback_summary": paths[u"general_fallback_summary"],
        u"faltantes_modelo_csv": paths[u"faltantes_modelo"],
    }


def _plant_entries(args, config):
    if args.all:
        return _discover_entries_from_project_dir()
    if not args.planta:
        raise ValueError(u"Indicar --planta P10|PP|TE|PR o usar --all.")

    plant = _u(args.planta).upper()
    cfg = dict(config.get(plant, {}))
    if cfg:
        if args.project:
            cfg[u"project"] = args.project
        if args.revit:
            cfg[u"revit_export"] = args.revit
        if args.output_dir:
            cfg[u"output_dir"] = args.output_dir
        revit_cfg = _u(cfg.get(u"revit_export"))
        revit_cli = _u(args.revit)
        if revit_cfg:
            revit_path = _abs_path(revit_cfg)
        elif revit_cli:
            revit_path = _abs_path(revit_cli)
        else:
            revit_path = _default_revit_export(plant)
        odir = cfg.get(u"output_dir")
        if odir:
            odir = _abs_path(odir)
        return [
            (
                plant,
                _resolve_project_xml_for_plant(plant, cfg.get(u"project"), args.project),
                revit_path,
                odir or _default_output_dir(plant),
            )
        ]

    odir_cli = _abs_path(args.output_dir) if args.output_dir else u""
    return [
        (
            plant,
            _resolve_project_xml_for_plant(plant, u"", args.project),
            _abs_path(args.revit) if args.revit else _default_revit_export(plant),
            odir_cli or _default_output_dir(plant),
        )
    ]


def main():
    parser = argparse.ArgumentParser(
        description=u"Cruza Project/Revit por planta sin escribir en Revit."
    )
    parser.add_argument(u"--planta", choices=PLANTAS_DEFAULT, help=u"Planta a procesar: P10, PP, TE o PR.")
    parser.add_argument(u"--all", action="store_true", help=u"Procesa todos los Project XML detectados en public/project.")
    parser.add_argument(u"--project", help=u"Ruta al Project XML de la planta indicada.")
    parser.add_argument(u"--revit", help=u"Ruta al CSV exportado de Revit de la planta indicada.")
    parser.add_argument(u"--output-dir", help=u"Carpeta de salida. Default: public/output/{PLANTA}.")
    parser.add_argument(u"--config", default=DEFAULT_CONFIG, help=u"Config JSON opcional de proyectos por planta.")
    parser.add_argument(
        u"--copy-to-public",
        action="store_true",
        help=u"Copia el confirmado de la planta procesada a public/match_project_revit_confirmado.csv.",
    )
    parser.add_argument(
        u"--cluster-mode",
        choices=[u"canonical", u"distributed"],
        default=u"distributed",
        help=u"TE/PP: canonical o distributed (default: distributed).",
    )
    parser.add_argument(
        u"--force-ancestor-container",
        action=u"store_true",
        help=(
            u"Activa modo force_ancestor_container también para P10/PR. "
            u"TE/PP: ya está activo por defecto."
        ),
    )
    parser.add_argument(
        u"--no-force-ancestor-container",
        action=u"store_true",
        help=u"Desactiva force_ancestor_container en TE/PP (por defecto allí está activo).",
    )
    args = parser.parse_args()

    if not os.path.isdir(INPUT_DIR):
        os.makedirs(INPUT_DIR)

    config = _load_config(_abs_path(args.config))
    results = []
    for plant, project_path, revit_path, output_dir in _plant_entries(args, config):
        print(u"Procesando {0}...".format(plant))
        result = run_plant(
            plant,
            project_path,
            revit_path,
            output_dir,
            copy_to_public=(args.copy_to_public and not args.all),
            cluster_mode=args.cluster_mode,
            force_ancestor_container=(
                True
                if args.force_ancestor_container
                else (False if args.no_force_ancestor_container else None)
            ),
        )
        results.append(result)
        print(u"  Project códigos: {0}".format(result[u"project_count"]))
        print(u"  Revit elementos: {0}".format(result[u"revit_count"]))
        print(u"  Salida: {0}".format(result[u"output_dir"]))
        print(u"  Faltantes modelo: {0}".format(result.get(u"faltantes_modelo_csv", u"")))
        print(u"  Diagnóstico GENERAL: {0}".format(result.get(u"general_fallback_csv", u"")))
        if result[u"copied_public"]:
            print(u"  Copiado a compatibilidad: {0}".format(result[u"copied_public"]))

    print(u"Listo. Plantas procesadas: {0}".format(u", ".join(r[u"planta"] for r in results)))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
from __future__ import print_function

from btz_manual_catalog import list_plants, list_sectors, list_subsectors, list_units, _u
from btz_manual_usage import count_plant, count_sector, count_subsector, used_subsectors_for_sector


def _label_used(count):
    if count > 0:
        return u"USADO:{0}".format(count)
    return u"LIBRE"


def _pick_yes_no(forms, title, message, yes_text=u"Sí", no_text=u"No"):
    picked = forms.CommandSwitchWindow.show(
        [yes_text, no_text],
        message=message,
        title=title,
    )
    return picked == yes_text


def pick_mode(forms):
    picked = forms.CommandSwitchWindow.show(
        [u"Asignar manual (01/02/03/04)", u"Reporte de uso (modelo completo)", u"Cancelar"],
        message=u"Elegí acción para BTZ manual",
        title=u"BTZ manual",
    )
    if picked == u"Asignar manual (01/02/03/04)":
        return u"assign"
    if picked == u"Reporte de uso (modelo completo)":
        return u"report"
    return u"cancel"


def pick_assignment(catalog, usage, forms):
    only_unused = _pick_yes_no(
        forms,
        title=u"BTZ manual",
        message=u"¿Mostrar solo opciones no usadas?",
        yes_text=u"Sí (solo no usados)",
        no_text=u"No (mostrar todo)",
    )

    plants = list_plants(catalog)
    if only_unused:
        plants = [p for p in plants if count_plant(usage, p[u"code"]) == 0]
    if not plants:
        forms.alert(u"No hay plantas disponibles con ese filtro.", title=u"BTZ manual", warn_icon=True)
        return None

    p_map = {}
    p_options = []
    for p in plants:
        used = count_plant(usage, p[u"code"])
        label = u"{0} | {1}".format(p[u"display"], _label_used(used))
        p_map[label] = p
        p_options.append(label)
    p_pick = forms.SelectFromList.show(
        sorted(p_options),
        title=u"Paso 1/4: Elegir planta -> BTZ_Description_01",
        button_name=u"Usar planta",
        multiselect=False,
        width=1000,
        height=640,
    )
    if not p_pick:
        return None
    plant = p_map.get(_u(p_pick))
    if plant is None:
        return None

    sectors = list_sectors(catalog, plant[u"code"])
    if only_unused:
        sectors = [s for s in sectors if count_sector(usage, s[u"write_code"]) == 0]
    if not sectors:
        forms.alert(u"No hay sectores disponibles para la planta elegida.", title=u"BTZ manual", warn_icon=True)
        return None

    s_map = {}
    s_options = []
    for s in sectors:
        used = count_sector(usage, s[u"write_code"])
        used_subs = used_subsectors_for_sector(usage, s[u"write_code"])
        hint = u"subsectors usados:{0}".format(len(used_subs))
        label = u"{0} | {1} | {2}".format(s[u"display"], _label_used(used), hint)
        s_map[label] = s
        s_options.append(label)
    add_sector_opt = u"(Agregar sector nuevo...)"
    s_options.append(add_sector_opt)
    s_pick = forms.SelectFromList.show(
        sorted(s_options),
        title=u"Paso 2/4: Elegir sector -> BTZ_Description_02",
        button_name=u"Usar sector",
        multiselect=False,
        width=1200,
        height=720,
    )
    if not s_pick:
        return None
    sector = s_map.get(_u(s_pick))
    created_sector = None
    if _u(s_pick) == add_sector_opt:
        sector_key = _u(forms.ask_for_string(
            default=u"",
            prompt=u"Codigo corto de sector (ej: PV)",
            title=u"Nuevo sector",
        )).upper()
        if not sector_key:
            return None
        sector_name = _u(forms.ask_for_string(
            default=sector_key,
            prompt=u"Nombre sector (ej: Plataforma Volcable)",
            title=u"Nuevo sector",
        ))
        default_write = u"{0}-{1}".format(_u(plant[u"code"]).upper(), sector_key)
        sector_write = _u(forms.ask_for_string(
            default=default_write,
            prompt=u"Codigo a escribir en BTZ_Description_02",
            title=u"Nuevo sector",
        )).upper()
        if not sector_write:
            return None
        sector = {
            u"key": sector_key,
            u"name": sector_name or sector_key,
            u"write_code": sector_write,
            u"display": u"{0} | {1} | cod:{2}".format(sector_key, sector_name or sector_key, sector_write),
        }
        created_sector = {
            u"key": sector_key,
            u"name": sector_name or sector_key,
            u"write_code": sector_write,
        }
    elif sector is None:
        return None

    subsectors = list_subsectors(catalog, plant[u"code"], sector[u"key"])
    if only_unused:
        subsectors = [x for x in subsectors if count_subsector(usage, x[u"code"]) == 0]

    subsector = None
    created_subsector = None
    if subsectors:
        ss_map = {u"(Sin subsector)": None}
        add_sub_opt = u"(Agregar subsector nuevo...)"
        ss_options = [u"(Sin subsector)", add_sub_opt]
        for ss in subsectors:
            used = count_subsector(usage, ss[u"code"])
            label = u"{0} | {1}".format(ss[u"display"], _label_used(used))
            ss_map[label] = ss
            ss_options.append(label)
        ss_pick = forms.SelectFromList.show(
            ss_options,
            title=u"Paso 3/4: Elegir subsector -> BTZ_Description_03",
            button_name=u"Usar subsector",
            multiselect=False,
            width=1200,
            height=720,
        )
        if ss_pick is None:
            return None
        if _u(ss_pick) == add_sub_opt:
            default_sub_code = u"{0}1".format(_u(sector[u"key"]).upper())
            sub_code = _u(forms.ask_for_string(
                default=default_sub_code,
                prompt=u"Codigo de subsector (ej: PV1)",
                title=u"Nuevo subsector",
            )).upper()
            if not sub_code:
                return None
            sub_name = _u(forms.ask_for_string(
                default=sub_code,
                prompt=u"Nombre de subsector (ej: Plataforma Volcable 1)",
                title=u"Nuevo subsector",
            ))
            subsector = {u"code": sub_code, u"name": sub_name or sub_code}
            created_subsector = {u"code": sub_code, u"name": sub_name or sub_code}
        else:
            subsector = ss_map.get(_u(ss_pick))
    else:
        add_sub = _pick_yes_no(
            forms,
            title=u"BTZ manual",
            message=u"No hay subsectores cargados para este sector.\n¿Queres crear uno nuevo ahora?",
            yes_text=u"Si, crear",
            no_text=u"No, continuar sin subsector",
        )
        if add_sub:
            default_sub_code = u"{0}1".format(_u(sector[u"key"]).upper())
            sub_code = _u(forms.ask_for_string(
                default=default_sub_code,
                prompt=u"Codigo de subsector (ej: PV1)",
                title=u"Nuevo subsector",
            )).upper()
            if not sub_code:
                return None
            sub_name = _u(forms.ask_for_string(
                default=sub_code,
                prompt=u"Nombre de subsector (ej: Plataforma Volcable 1)",
                title=u"Nuevo subsector",
            ))
            subsector = {u"code": sub_code, u"name": sub_name or sub_code}
            created_subsector = {u"code": sub_code, u"name": sub_name or sub_code}

    unit = None
    if subsector:
        units = list_units(catalog, plant[u"code"], sector[u"key"], subsector[u"code"])
        if units:
            u_map = {u"(Sin unidad)": None}
            u_options = [u"(Sin unidad)"]
            for uu in units:
                label = uu[u"display"]
                u_map[label] = uu
                u_options.append(label)
            u_pick = forms.SelectFromList.show(
                u_options,
                title=u"Paso 4/4: Elegir unidad puntual -> BTZ_Description_04",
                button_name=u"Usar unidad",
                multiselect=False,
                width=1200,
                height=720,
            )
            if u_pick is None:
                return None
            unit = u_map.get(_u(u_pick))

    overwrite = _pick_yes_no(
        forms,
        title=u"BTZ manual",
        message=u"¿Permitir sobrescribir valores existentes en la selección?",
        yes_text=u"Sí, sobrescribir",
        no_text=u"No, respetar existentes",
    )

    preview = [
        u"Vista previa de escritura:",
        u"BTZ_Description_01 (planta): {0}".format(plant[u"code"]),
        u"BTZ_Description_02 (sector): {0}".format(sector[u"write_code"]),
        u"BTZ_Description_03 (subsector): {0}".format(subsector[u"code"] if subsector else u"(vacío)"),
        u"BTZ_Description_04 (unidad): {0}".format(unit[u"code"] if unit else u"(vacío)"),
    ]
    ok = _pick_yes_no(
        forms,
        title=u"BTZ manual",
        message=u"\n".join(preview) + u"\n\n¿Confirmar asignación?",
        yes_text=u"Confirmar",
        no_text=u"Cancelar",
    )
    if not ok:
        return None

    return {
        u"only_unused": only_unused,
        u"overwrite": overwrite,
        u"plant_code": plant[u"code"],
        u"plant_name": plant[u"name"],
        u"sector_key": sector[u"key"],
        u"sector_write_code": sector[u"write_code"],
        u"sector_name": sector[u"name"],
        u"subsector_code": subsector[u"code"] if subsector else u"",
        u"subsector_name": subsector[u"name"] if subsector else u"",
        u"unit_code": unit[u"code"] if unit else u"",
        u"unit_name": unit[u"name"] if unit else u"",
        u"created_sector": created_sector,
        u"created_subsector": created_subsector,
    }

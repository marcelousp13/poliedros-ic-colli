bl_info = {
    "name": "Gerador de Sólidos (Mínimo Global)",
    "blender": (4, 0, 0),
    "category": "Object",
    "version": (1, 4),
    "author": "Thomas",
    "description": "Importa soluções de mínimos globais em JSON e exporta STL diretamente para impressão 3D."
}

import bpy
import json
import os
import mathutils
import importlib
import addon_utils
from bpy.types import Operator, Panel
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper

# =========================================================
# Funções auxiliares
# =========================================================

def carregar_json(filepath):
    """Lê o JSON de solução global e retorna vértices e faces."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Identifica lista de pontos
    if "vc" in data and isinstance(data["vc"], list):
        pontos = data["vc"]
    elif "vertices" in data and isinstance(data["vertices"], list):
        pontos = data["vertices"]
    else:
        raise ValueError("JSON não contém chaves válidas ('vc' ou 'vertices').")

    vertices = [mathutils.Vector(v) for v in pontos]

    # Gera faces por convex hull
    import bmesh
    mesh_temp = bpy.data.meshes.new("temp_mesh")
    bm = bmesh.new()
    for v in vertices:
        bm.verts.new(v)
    bm.verts.ensure_lookup_table()
    bmesh.ops.convex_hull(bm, input=bm.verts)
    bm.to_mesh(mesh_temp)
    bm.free()

    faces = [list(p.vertices) for p in mesh_temp.polygons] 
    bpy.data.meshes.remove(mesh_temp)

    return vertices, faces, data.get("nome", "MinimoGlobal")


def criar_objeto(nome, vertices, faces):
    """Cria o objeto 3D."""
    mesh = bpy.data.meshes.new(nome)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(nome, mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    return obj


def export_stl_fallback(obj, filepath):
    """
    Exportador ASCII-STL fallback que não depende de addons.
    Usa o mesh avaliado (com modifiers aplicados) para exportar triângulos.
    """
    # Garante depsgraph para pegar o mesh avaliado (modifiers aplicados)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)

    # Obtém mesh temporário
    mesh = eval_obj.to_mesh()

    if mesh is None:
        raise RuntimeError("Não foi possível obter mesh avaliado para o objeto.")

    name = obj.name.replace(" ", "_")
    # Escreve ASCII STL
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"solid {name}\n")
        for poly in mesh.polygons:
            n = poly.normal
            f.write(f"  facet normal {n.x:.6e} {n.y:.6e} {n.z:.6e}\n")
            f.write("    outer loop\n")
            for vi in poly.vertices:
                v = mesh.vertices[vi].co
                f.write(f"      vertex {v.x:.6e} {v.y:.6e} {v.z:.6e}\n")
            f.write("    endloop\n")
            f.write("  endfacet\n")
        f.write(f"endsolid {name}\n")

    # libera o mesh avaliado (API compatível com versões recentes)
    try:
        eval_obj.to_mesh_clear()
    except Exception:
        # fallback (algumas builds podem usar outro nome)
        try:
            bpy.data.meshes.remove(mesh)
        except Exception:
            pass


# =========================================================
# Operadores
# =========================================================

class IMPORT_OT_solucao_global(Operator):
    """Importar JSON de mínimo global"""
    bl_idname = "object.importar_solucao_global"
    bl_label = "Importar Mínimo Global"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        try:
            vertices, faces, nome = carregar_json(self.filepath)
            obj = criar_objeto(nome, vertices, faces)
            self.report({'INFO'}, f"Solução '{nome}' importada com sucesso ({len(vertices)} vértices).")
        except Exception as e:
            self.report({'ERROR'}, f"Erro ao importar: {str(e)}")
            return {'CANCELLED'}
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class EXPORT_OT_solucao_global_stl(Operator, ExportHelper):
    """Exportar STL"""
    bl_idname = "object.exportar_solucao_global_stl"
    bl_label = "Exportar STL"
    bl_description = "Exporta o sólido selecionado como arquivo STL"
    bl_options = {'REGISTER'}

    filename_ext = ".stl"
    filter_glob: StringProperty(default="*.stl", options={'HIDDEN'})

    def execute(self, context):
        try:
            obj = context.active_object
            if not obj:
                self.report({'ERROR'}, "Nenhum objeto selecionado.")
                return {'CANCELLED'}

            filepath = bpy.path.abspath(self.filepath)

            # 1) Tenta usar o addon io_mesh_stl (ativando-o se necessário)
            stl_exported = False
            try:
                # Tenta ativar o addon (se já ativado, não altera)
                addon_utils.enable("io_mesh_stl", default_set=True)
                # Recarrega caso já esteja importado
                if "io_mesh_stl" in locals():
                    importlib.reload(io_mesh_stl)  # type: ignore
                # Tenta importar o módulo de exportação
                import io_mesh_stl.export_stl as export_stl  # type: ignore

                # alguns ambientes definem save(...) e outros usam função diferente;
                # aqui tentamos chamar save (interface do addon oficial)
                try:
                    export_stl.save(operator=self, context=context, filepath=filepath, use_selection=True)
                    stl_exported = True
                except Exception:
                    # fallback para operador (se registrado)
                    try:
                        bpy.ops.export_mesh.stl(filepath=filepath, use_selection=True)
                        stl_exported = True
                    except Exception:
                        stl_exported = False

            except Exception:
                stl_exported = False

            # 2) Se não funcionou, usa o fallback ASCII-STL implementado
            if not stl_exported:
                try:
                    export_stl_fallback(obj, filepath)
                    stl_exported = True
                except Exception as e:
                    # último recurso: reporta erro com detalhe
                    self.report({'ERROR'}, f"Falha ao exportar via fallback: {e}")
                    return {'CANCELLED'}

            # Salva o caminho na cena para mostrar no painel
            context.scene.last_stl_export_path = filepath

            self.report({'INFO'}, f"STL exportado com sucesso: {filepath}")
            print(f"[Gerador de Sólidos] STL salvo em: {filepath}")

        except Exception as e:
            self.report({'ERROR'}, f"Erro ao exportar STL: {str(e)}")
            return {'CANCELLED'}

        return {'FINISHED'}


# =========================================================
# Painel da Interface
# =========================================================

class GERADOR_PT_Painel(Panel):
    bl_label = "Gerador de Sólidos (Mínimo Global)"
    bl_idname = "OBJECT_PT_gerador_minimo_global"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Gerador de sólidos"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.operator("object.importar_solucao_global", icon="FILE_FOLDER")
        layout.operator("object.exportar_solucao_global_stl", icon="EXPORT")

        layout.separator()

        if scene.get("last_stl_export_path"):
            layout.label(text="Último STL exportado:")
            # mostra apenas o nome do arquivo e permite copiar com tooltip
            layout.label(text=os.path.basename(scene.last_stl_export_path))
            # botão para abrir pasta (funciona em Windows / macOS / Linux)
            row = layout.row()
            op = row.operator("object.open_stl_folder", text="Abrir pasta do STL", icon="FILE_FOLDER")
            op.filepath = scene.last_stl_export_path
        else:
            layout.label(text="Nenhum STL exportado ainda.")


class OPEN_STL_FOLDER_OT(Operator):
    """Abre a pasta do último STL exportado no gerenciador de arquivos do SO"""
    bl_idname = "object.open_stl_folder"
    bl_label = "Abrir pasta STL"
    filepath: StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        path = bpy.path.abspath(self.filepath)
        folder = os.path.dirname(path)
        if not os.path.exists(folder):
            self.report({'ERROR'}, "Pasta não encontrada.")
            return {'CANCELLED'}
        # Abre pasta dependendo do SO
        if os.name == 'nt':  # Windows
            os.startfile(folder)
        else:
            import subprocess, sys
            if sys.platform == 'darwin':  # macOS
                subprocess.call(["open", folder])
            else:  # linux variants
                subprocess.call(["xdg-open", folder])
        return {'FINISHED'}


# =========================================================
# Registro
# =========================================================

classes = [
    IMPORT_OT_solucao_global,
    EXPORT_OT_solucao_global_stl,
    GERADOR_PT_Painel,
    OPEN_STL_FOLDER_OT,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.last_stl_export_path = bpy.props.StringProperty(
        name="Último STL Exportado",
        default=""
    )


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.last_stl_export_path


if __name__ == "__main__":
    register()

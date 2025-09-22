import bpy
import socket
import json
import queue
import threading

HOST = "127.0.0.1"
PORT = 5000

# Shared queue for commands coming from the socket
command_queue = queue.Queue()


# ------------------------------------------------------------
# 1. Blender-side: Execute a single command
# ------------------------------------------------------------
def execute_command(cmd):
    action = cmd.get("action")
    params = cmd.get("params", {})

    try:
        if action == "add_cube":
            bpy.ops.mesh.primitive_cube_add(
                size=params.get("size", 1),
                location=params.get("location", (0, 0, 0)),
                rotation=params.get("rotation", (0, 0, 0)),
            )
            return {"status": "ok", "message": "Cube added"}

        elif action == "add_sphere":
            bpy.ops.mesh.primitive_uv_sphere_add(
                radius=params.get("radius", 1),
                location=params.get("location", (0, 0, 0)),
            )
            return {"status": "ok", "message": "Sphere added"}

        elif action == "add_plane":
            bpy.ops.mesh.primitive_plane_add(
                size=params.get("size", 2),
                location=params.get("location", (0, 0, 0)),
            )
            return {"status": "ok", "message": "Plane added"}

        elif action == "add_cylinder":
            bpy.ops.mesh.primitive_cylinder_add(
                radius=params.get("radius", 1),
                depth=params.get("depth", 2),
                location=params.get("location", (0, 0, 0))
            )
            return {"status": "ok", "message": "Cylinder added"}

        elif action == "add_cone":
            bpy.ops.mesh.primitive_cone_add(
                radius1=params.get("radius1", 1),
                radius2=params.get("radius2", 0),
                depth=params.get("depth", 2),
                location=params.get("location", (0, 0, 0))
            )
            return {"status": "ok", "message": "Cone added"}
            
  
        elif action == "move_object":
            obj = bpy.data.objects.get(params["object_name"])
            if obj:
                obj.location = params.get("location", obj.location)
                return {"status": "ok", "message": "Object moved"}
            return {"status": "error", "message": "Object not found"}

        elif action == "rotate_object":
            obj = bpy.data.objects.get(params["object_name"])
            if obj:
                obj.rotation_euler = params.get("rotation", obj.rotation_euler)
                return {"status": "ok", "message": "Object rotated"}
            return {"status": "error", "message": "Object not found"}

        elif action == "scale_object":
            obj = bpy.data.objects.get(params["object_name"])
            if obj:
                obj.scale = params.get("scale", obj.scale)
                return {"status": "ok", "message": "Object scaled"}
            return {"status": "error", "message": "Object not found"}
            

        elif action == "add_camera":
            cam_data = bpy.data.cameras.new(name=params.get("name", "Camera"))
            cam_obj = bpy.data.objects.new(cam_data.name, cam_data)
            bpy.context.collection.objects.link(cam_obj)
            cam_obj.location = params.get("location", (3, -3, 2))
            bpy.context.scene.camera = cam_obj
            return {"status": "ok", "message": "Camera added"}

        elif action == "add_point_light":
            light_data = bpy.data.lights.new(
                name=params.get("name", "PointLight"), type="POINT"
            )
            light_data.energy = params.get("energy", 1000)
            light_obj = bpy.data.objects.new(light_data.name, light_data)
            bpy.context.collection.objects.link(light_obj)
            light_obj.location = params.get("location", (0, 0, 5))
            return {"status": "ok", "message": "Point light added"}

        elif action == "add_sun_light":
            light_data = bpy.data.lights.new(name=params.get("name","SunLight"), type='SUN')
            light_data.energy = params.get("strength",3.0)
            light_obj = bpy.data.objects.new(light_data.name, light_data)
            bpy.context.collection.objects.link(light_obj)
            light_obj.rotation_euler = params.get("rotation",(0,0,0))
            return {"status":"ok","message":"Sun light added"}


        elif action == "set_material_color":
            obj = bpy.data.objects.get(params["object_name"])
            if obj:
                mat = bpy.data.materials.new(name=f"{obj.name}_Mat")
                mat.use_nodes = True
                bsdf = mat.node_tree.nodes.get("Principled BSDF")
                if bsdf:
                    bsdf.inputs["Base Color"].default_value = tuple(params.get("color",(1,1,1,1)))
                obj.data.materials.append(mat)
                return {"status":"ok","message":"Material color set"}
            return {"status":"error","message":"Object not found"}

        elif action == "render":
            filepath = params.get("filepath", "/tmp/render.png")
            bpy.context.scene.render.filepath = filepath
            bpy.ops.render.render(write_still=True)
            return {"status": "ok", "message": f"Rendered to {filepath}"}

        elif action == "list_objects":
            objs = [
                {"name": o.name, "type": o.type, "location": tuple(o.location)}
                for o in bpy.context.scene.objects
            ]
            return {"status": "ok", "objects": objs}
            
        elif action == "delete_object":
            obj = bpy.data.objects.get(params["object_name"])
            if obj:
                bpy.data.objects.remove(obj, do_unlink=True)
                return {"status":"ok","message":"Object deleted"}
            return {"status":"error","message":"Object not found"}

        elif action == "clear_scene":
            #bpy.ops.wm.read_factory_settings(use_empty=True)
            #return {"status": "ok", "message": "Scene cleared"}
            # Deselect everything first
            bpy.ops.object.select_all(action='SELECT')
            # Delete selected objects
            bpy.ops.object.delete(use_global=False)
        
            # Optionally clear orphan data like meshes/materials:
            for block in bpy.data.meshes:
                bpy.data.meshes.remove(block)
            for block in bpy.data.materials:
                bpy.data.materials.remove(block)

            return {"status": "ok", "message": "Scene cleared"}

        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


# ------------------------------------------------------------
# 2. Thread: listen for socket connections and enqueue commands
# ------------------------------------------------------------
def socket_listener():
    print(f"Blender socket server listening on {HOST}:{PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen(5)
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


def handle_client(conn, addr):
    try:
        data = conn.recv(65536)
        if not data:
            return
        cmd = json.loads(data.decode())
        command_queue.put((cmd, conn))
    except Exception as e:
        err = json.dumps({"status": "error", "message": str(e)}).encode()
        try:
            conn.sendall(err)
        finally:
            conn.close()


# ------------------------------------------------------------
# 3. Blender timer: process queued commands without blocking GUI
# ------------------------------------------------------------
def process_queue():
    try:
        while True:
            cmd, conn = command_queue.get_nowait()
            result = execute_command(cmd)
            conn.sendall(json.dumps(result).encode())
            conn.close()
    except queue.Empty:
        pass
    # Re-run every 0.1 seconds to keep the viewport responsive
    return 0.1


# ------------------------------------------------------------
# 4. Start everything
# ------------------------------------------------------------
def start():
    threading.Thread(target=socket_listener, daemon=True).start()
    bpy.app.timers.register(process_queue)


if __name__ == "__main__":
    start()

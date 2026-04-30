import open3d as o3d

def save_glb_thumbnail(glb_path, output_path="output.png"):
    mesh = o3d.io.read_triangle_mesh(glb_path)

    if mesh.is_empty():
        print("❌ Failed to load mesh")
        return

    mesh.compute_vertex_normals()

    vis = o3d.visualization.Visualizer()
    vis.create_window(visible=True)  # MUST be visible on Windows

    vis.add_geometry(mesh)
    vis.poll_events()
    vis.update_renderer()

    # Capture image
    vis.capture_screen_image(output_path)
    print(f"✅ Saved: {output_path}")

    vis.destroy_window()


glb_file = "models/wedding_asset_1777308413.glb"
save_glb_thumbnail(glb_file)
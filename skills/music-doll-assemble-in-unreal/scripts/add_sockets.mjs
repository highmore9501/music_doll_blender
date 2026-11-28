// 在骨骼网格上建挂件 socket（Python 建不了 SkeletalMeshSocket，所以走 MCP 的 skeletal_mesh 工具集）。
//
// 跑法（本机有 MCP 客户端包装器时）：
//   node ue.mjs run add_sockets.mjs
// 这个文件导出的是一个 (ue) => Promise<object> 的函数，ue.call(工具集, 工具名, 参数) 就是 MCP 调用。

const MESH_PATH = "/Game/MyCharacters/米娅鼓手/米娅-星彩_body.米娅-星彩_body";

// socket 名 → 骨名。骨名从 manifest.json 的 assembly.bone_parts 里抄，别自己猜。
const SOCKETS = [
    { socket: "Stick_L", bone: "左手首" },
    { socket: "Stick_R", bone: "右手首" },
];

export default async function (ue) {
    const toolset = "editor_toolset.toolsets.skeletal_mesh.SkeletalMeshTools";
    const mesh = { refPath: MESH_PATH };
    const outcome = { mesh: MESH_PATH, created: [], errors: [] };

    const identity = {
        location: { x: 0, y: 0, z: 0 },
        rotation: { pitch: 0, yaw: 0, roll: 0 },
        scale: { x: 1, y: 1, z: 1 },
    };

    for (const { socket, bone } of SOCKETS) {
        const added = await ue.call(toolset, "add_socket", { mesh, socket_name: socket, bone_name: bone });
        if (added.isError) {
            outcome.errors.push({ socket, step: "add_socket", text: added.text.slice(0, 300) });
            continue;
        }
        // 相对变换必须是 0：导出时已经把骨的世界矩阵的逆乘进顶点里了
        const positioned = await ue.call(toolset, "set_socket_transform", { mesh, socket_name: socket, transform: identity });
        if (positioned.isError) {
            outcome.errors.push({ socket, step: "set_socket_transform", text: positioned.text.slice(0, 300) });
        }
        const check = await ue.call(toolset, "get_socket_bone", { mesh, socket_name: socket });
        outcome.created.push({ socket, bone, verify: check.text.trim().slice(0, 200) });
    }

    // 存盘，否则关掉编辑器 socket 就没了
    const saved = await ue.call("editor_toolset.toolsets.asset.AssetTools", "save_assets", {
        asset_paths: [MESH_PATH.split(".")[0]],
    });
    outcome.saved = saved.text.slice(0, 200);
    return outcome;
}

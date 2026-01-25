from typing import Any, Self, cast

import bpy
from mathutils import Vector

AttrsDict = dict[str, Any]
IOValue = float | int | str | Vector | tuple[str, int | str]
InputsDef = dict[str, tuple[str, AttrsDict]]
NodesDef = dict[str, tuple[str, AttrsDict, dict[int | str, IOValue]]]
OutputsDef = dict[str, tuple[str, AttrsDict, IOValue]]


def setup_node_tree(node_tree: bpy.types.NodeTree, nodes_def: NodesDef, label_nodes: bool = True):
    nodes = node_tree.nodes
    links = node_tree.links

    _check_type(nodes_def, dict)
    for name, (node_type, attrs, inputs) in nodes_def.items():
        node = nodes.new(node_type)
        node.name = name
        if label_nodes:
            node.label = " ".join((word.capitalize() for word in name.split("_")))

        _check_type(attrs, dict)
        for attr, value in attrs.items():
            setattr(node, attr, value)

        _check_type(inputs, dict)
        for input_index, value in inputs.items():
            if isinstance(value, tuple):
                try:
                    from_node, output_index = value
                except ValueError:
                    raise ValueError(f"failed to unpack '{value}', expected '(node, index)'")
                links.new(nodes[from_node].outputs[output_index], node.inputs[input_index])
            else:
                node.inputs[input_index].default_value = value  # pyright: ignore[reportAttributeAccessIssue]


class CustomNodetreeNodeBase(bpy.types.ShaderNodeCustomGroup):
    def init_node_tree(self, inputs_def: InputsDef, nodes_def: NodesDef, outputs_def: OutputsDef):
        name = f"CUSTOM_NODE_{self.__class__.__name__}"
        node_tree = bpy.data.node_groups.new(name, "ShaderNodeTree")
        nodes = node_tree.nodes
        links = node_tree.links
        interface = node_tree.interface
        assert interface

        for name, (socket_type, attrs) in inputs_def.items():
            socket = interface.new_socket(name, in_out="INPUT", socket_type=socket_type)

            _check_type(attrs, dict)
            for attribute, value in attrs.items():
                setattr(socket, attribute, value)

        node_input = nodes.new("NodeGroupInput")
        node_input.name = "inputs"

        setup_node_tree(node_tree, nodes_def)

        node_output = nodes.new("NodeGroupOutput")
        node_output.name = "outputs"

        for name, (socket_type, attrs, output_value) in outputs_def.items():
            socket = interface.new_socket(name, in_out="OUTPUT", socket_type=socket_type)

            _check_type(attrs, dict)
            for attribute, value in attrs.items():
                setattr(socket, attribute, value)

            if isinstance(output_value, tuple):
                from_node, output_index = output_value
                links.new(nodes[from_node].outputs[output_index], node_output.inputs[name])
            else:
                node_output.inputs[name].default_value = output_value  # pyright: ignore[reportAttributeAccessIssue]

        self.node_tree = node_tree

    def copy(self, node: bpy.types.Node):
        node = cast(Self, node)
        if node.node_tree is None:
            self.node_tree = None
        else:
            self.node_tree = node.node_tree.copy()

    def free(self):
        if self.node_tree and self.node_tree.users < 1:
            bpy.data.node_groups.remove(self.node_tree)

    def draw_buttons(self, context: bpy.types.Context, layout: bpy.types.UILayout):
        for prop in self.bl_rna.properties:
            if prop.is_runtime and not prop.is_readonly:
                text = "" if prop.type == "ENUM" else prop.name
                layout.prop(self, prop.identifier, text=text)


def _check_type(value: Any, expected_type: type):
    if not isinstance(value, expected_type):
        raise TypeError(f"{value} has type '{type(value).__name__}', expected '{type.__name__}'")


class SharedCustomNodetreeNodeBase(CustomNodetreeNodeBase):
    def init_node_tree(self, inputs_def: InputsDef, nodes_def: NodesDef, outputs_def: OutputsDef):
        name = f"CUSTOM_NODE_{self.__class__.__name__}"
        if node_tree := bpy.data.node_groups.get(name):
            assert isinstance(node_tree, bpy.types.ShaderNodeTree)
            self.node_tree = node_tree
        else:
            super().init_node_tree(inputs_def, nodes_def, outputs_def)

    def copy(self, node: bpy.types.Node):
        self.node_tree = cast(Self, node).node_tree

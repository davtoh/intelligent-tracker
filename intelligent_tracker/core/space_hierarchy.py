"""Hierarchy resolution, child registration, and family tree traversal mixin for Space."""

import gc

from intelligent_tracker.core.weakref_utils import WeakWatcherWithData


class SpaceHierarchyMixin:
    """Mixin encapsulating hierarchical tree traversal and child management for Space."""

    _space_entities = None
    _space_collect_entities = True

    def _space_correct_hierarchy(self, old_hierarchy):
        """
        private function used to correct an old hierarchy of this
        object and all its children.

        :param old_hierarchy: string of the previous hierarchy
        """
        # register new hierarchy
        new_hierarchy = self._space_hierarchy()
        # change old hierarchy
        self._space_entities[new_hierarchy] = self._space_entities.pop(old_hierarchy)
        # change children's old hierarchies
        for i in self._space_children.values():
            i = i()
            old = new_hierarchy + "." + i.name
            new = old_hierarchy + "." + i.name
            self._space_entities[old] = self._space_entities.pop(new)

    @staticmethod
    def _space_collect():
        """This process is expensive so do not use if not needed"""
        gc.collect()  # force to collect and update space

    def _space_hierarchy(self, key=None, use_name=True):
        """
        get hierarchy of this object

        :param key: name of append in hierarchy. None to not append
        :param use_name: whether to use the name of this object. That is
            if True get the hierarchy until me and append key=child,
            if False get the hierarchy until parent and append key=brother
        :return: hierarchy
        """
        parent = self._space_parent_
        train = []
        if parent is not None:
            train.append(parent._space_hierarchy())
        if use_name:
            train.append(self.name)
        if key is not None:
            train.append(key)
        return ".".join(train)

    def _space_hierarchy_in_space(self, hierarchy):
        """
        check a hierarchy is already in the space

        :param hierarchy: string of hierarchy
        :return: True if hierarchy in space else False
        """
        if hierarchy in self._space_entities:
            if self._space_collect_entities:
                self._space_collect()
            return hierarchy in self._space_entities
        else:
            return False

    def _space_parent_in_parents(self, parent):
        """
        check a parent is already in the family tree of this object

        :param parent: parent to check in tree
        :return: True if parent in tree else False
        """
        parent_ = parent._space_parent_
        if parent_ is None:
            return False
        elif parent_ is self:
            return True
        else:
            return self._space_parent_in_parents(parent_)

    def _space_add_child(self, child):
        """
        add an object in the internal children to appear in the Space
        as inside this object.

        :param child: child Space object
        """
        name = child.name
        if name in self._space_children:
            if self._space_children[name]() is not child:
                raise KeyError(f"conflicting name '{child.name}' in children of "
                               f"parent '{self.name}'")
            else:
                struct = self._space_children[name]
                struct._count += 1
                return

        child_ref = WeakWatcherWithData(child)
        child_ref._count = 0
        self._space_children[name] = child_ref
        child._space_name_handles.add(self._space_children)

    def _space_remove_child(self, child):
        """
        remove an object in the internal children to disappear in the Space
        as inside this object.

        :param child: child Space object
        """
        name = child.name
        struct = self._space_children[name]
        struct._count -= 1
        if struct._count <= 0:
            del self._space_children[name]
            child._space_name_handles.remove(self._space_children)

    def _space_delete(self):
        """
        delete Space object to outer Space. That is from all Space
        objects like Groups, parents and containers.
        """
        self._space_parent = None  # break any parent relationship
        name = self.name
        for handle in list(self._space_name_handles):
            handle.remove_name(name)


"""Graph completeness and association solver for polygonal connection matching."""

from collections import OrderedDict
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import numpy as np

from intelligent_tracker.geometry.polygons import PolyLine
from intelligent_tracker.geometry.primitives import NotInvertible


def _associate_single_references(completeness: "Completeness", groups: List[Any]):
    groups_ints = []
    groups_sets = []
    for id_key, refs in groups:
        try:
            if len(id_key[1]) == 1:
                groups_ints.append((id_key, list(refs)[0]))
            else:
                groups_sets.append((id_key, list(refs)[0]))
        except TypeError:
            groups_ints.append((id_key, list(refs)[0]))

    ints_in_sets = []
    for id_key, ref in groups_ints:
        pos = []
        ccnt_id, ckey = id_key
        for i, ((cnt_id, key), _) in enumerate(groups_sets):
            if ccnt_id == cnt_id and any(k in key for k in ckey):
                pos.append(i)
        ints_in_sets.append((pos, id_key, ref))
    ints_in_sets.sort(key=lambda x: len(x[0]))

    groups2 = []
    for pos, id_key, ref in ints_in_sets:
        assert len(pos) < 3
        while len(pos) > 0:
            r = pos[0]
            for c, _, _ in ints_in_sets:
                try:
                    c.remove(r)
                except ValueError:
                    pass
            groups2.append((id_key, (ref, groups_sets[r][1])))

    for id_key, refs in groups2:
        i = [(r.id_in_ids(id_key), r) for r in refs]
        i.sort(key=lambda x: (len(x[0]), not isinstance(x[1], PolyLine)))
        completeness.associate(i)


def _associate_complex_groups(completeness: "Completeness", groups: List[Any]):
    pill = 0
    for id_key, refs in groups:
        for r in refs:
            if r._group_id is None:
                r.give_group_id(pill)
                i = [(r.id_in_ids(id_key), r) for r in refs if r._group_id == pill]
                if len(i) == 2:
                    completeness.associate(i)
                pill += 1


class Completeness:
    """Search space to add BasePoly objects and find associations."""

    def __init__(self):
        self._references: Dict[Any, List[Any]] = {}

    def add_id(self, id, item):
        if id is None:
            raise Exception("None is not id")
        try:
            ref = self._references[id]
        except KeyError:
            self._references[id] = ref = [0, set()]
        ref[0] += 1
        ref[1].add(item)

    def sub_id(self, id, item):
        ref = self._references[id]
        ref[0] += 1
        ref[1].remove(item)

    def register(self, item):
        """Register Connection ids."""
        if (len(item) == 1 and item.id_left == item.id_right and
                (item.port_left is None or item.port_right is None)):
            self.add_id(item.id_left, item)
        else:
            if item.port_left is None:
                self.add_id(item.id_left, item)
            if item.port_right is None:
                self.add_id(item.id_right, item)

    def unregister(self, item):
        """Unregister all ids from a Connection."""
        if item.port_left is not None:
            self.sub_id(item.id_left, item)
        if item.port_right is not None:
            self.sub_id(item.id_right, item)

    def items_counts(self) -> Iterator[Tuple[Any, int]]:
        """Iterate over (id, count)."""
        for id_key, (count, _) in self._references.items():
            yield id_key, count

    def items_connections(self) -> Iterator[Tuple[Any, Set[Any]]]:
        """Iterate over (id, references to connections)."""
        for id_key, (_, ref) in self._references.items():
            yield id_key, ref

    def generate_count_dictionary(self) -> OrderedDict:
        """Get ordered dictionary of count of associations."""
        counts = np.sort(np.unique([i for i, _ in self._references.values()]))
        count_dict = OrderedDict([(c, []) for c in counts])
        for k, (count, ref) in self._references.items():
            count_dict[count].append((k, ref))
        return count_dict

    def generate_incomplete_set(self) -> Set[Any]:
        """Create a set with all missing ids."""
        incomplete = set()
        for link, link_sum in self.items_counts():
            if link_sum % 2:
                id_key, indexes = link
                try:
                    for index in indexes:
                        incomplete.add((id_key, index))
                except TypeError:
                    incomplete.add(link)
        return incomplete

    def create_associations(self):
        """Associate connections across all recorded references."""
        count_groups = self.generate_count_dictionary()
        for count, groups in count_groups.items():
            if count == 1:
                _associate_single_references(self, groups)
            elif count == 2:
                for id_key, refs in groups:
                    i = [(r.id_in_ids(id_key), r) for r in refs]
                    i.sort(key=lambda x: (len(x[0]), not isinstance(x[1], PolyLine)))
                    self.associate(i)
            elif count == 3:
                for id_key, refs in groups:
                    i = [(r.id_in_ids(id_key), r) for r in refs]
                    i.sort(key=lambda x: (len(x[0]), not isinstance(x[1], PolyLine)))
                    indeces_l, c_l = i.pop()
                    if len(indeces_l) == 2:
                        self.associate(i[0], (indeces_l, c_l))
                        self.associate(i[1], (indeces_l, c_l))
            else:
                _associate_complex_groups(self, groups)

    def associate(self, *args):
        if len(args) == 1:
            (indeces0, c0), (indeces1, c1) = args[0]
        elif len(args) == 2:
            (indeces0, c0), (indeces1, c1) = args[0], args[1]
        else:
            indeces0, c0, indeces1, c1 = args

        index0 = indeces0[0]
        p1 = c1.ports
        if indeces0 == indeces1:
            try:
                c1.invert()
                c0.give_port_in_index(index0, c1)
            except NotInvertible:
                c0.invert(force=True)
                c0.give_port_in_index(not index0, c1)
        elif len(indeces1) == 2:
            if p1[not index0] is None:
                c0.give_port_in_index(index0, c1)
            else:
                try:
                    c1.invert()
                    c0.give_port_in_index(index0, c1)
                except NotInvertible:
                    c0.invert(force=True)
                    c0.give_port_in_index(not index0, c1)
        else:
            c0.give_port_in_index(index0, c1)

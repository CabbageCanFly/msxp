from tools.build_local_items import drops


def test_drops_read_names_from_alt_text_or_the_label_after_the_icon():
    page = ('<img src="https://cdn.meowdb.com/icons/4000005.png" alt="Tree Branch" width="32"/>'
            '<img src="https://cdn.meowdb.com/icons/4010001.png" alt="" width="32" class="w-8"/><span class="min-w-0">Iron Ore</span>'
            '<img src="https://cdn.meowdb.com/icons/4000005.png" alt="" width="32"/><span>Tree Branch</span>'
            '<img src="https://cdn.meowdb.com/icons/9999999.png" alt="" width="32"/>')
    assert drops(page) == {4000005: 'Tree Branch', 4010001: 'Iron Ore'}

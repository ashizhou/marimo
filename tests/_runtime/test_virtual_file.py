# Copyright 2024 Marimo. All rights reserved.
from __future__ import annotations

from marimo._runtime.context import get_context
from marimo._runtime.requests import DeleteCellRequest
from marimo._runtime.runtime import Kernel
from tests.conftest import ExecReqProvider


async def test_virtual_file_creation(
    execution_kernel: Kernel, exec_req: ExecReqProvider
) -> None:
    k = execution_kernel
    await k.run(
        [
            exec_req.get(
                """
                import io
                import marimo as mo
                bytestream = io.BytesIO(b"hello world")
                pdf_plugin = mo.pdf(bytestream)
                """
            ),
        ]
    )
    assert len(get_context().virtual_file_registry.registry) == 1
    for fname in get_context().virtual_file_registry.registry.keys():
        assert fname.endswith(".pdf")


async def test_virtual_file_deletion(
    execution_kernel: Kernel, exec_req: ExecReqProvider
) -> None:
    k = execution_kernel
    await k.run(
        [
            er := exec_req.get(
                """
                import io
                import marimo as mo
                bytestream = io.BytesIO(b"hello world")
                pdf_plugin = mo.pdf(bytestream)
                """
            ),
        ]
    )
    assert len(get_context().virtual_file_registry.registry) == 1
    for fname in get_context().virtual_file_registry.registry.keys():
        assert fname.endswith(".pdf")

    await k.delete_cell(DeleteCellRequest(cell_id=er.cell_id))
    assert not get_context().virtual_file_registry.registry


async def test_cached_virtual_file_not_deleted(
    execution_kernel: Kernel, exec_req: ExecReqProvider
) -> None:
    k = execution_kernel
    await k.run(
        [
            exec_req.get(
                """
                import io
                import marimo as mo
                import functools
                """
            ),
            vfile_cache := exec_req.get(
                """
                @functools.lru_cache()
                def create_vfile(arg):
                    del arg
                    bytestream = io.BytesIO(b"hello world")
                    return mo.pdf(bytestream)
                """
            ),
            create_vfile_1 := exec_req.get("create_vfile(1)"),
        ]
    )
    assert len(get_context().virtual_file_registry.registry) == 1

    # Rerun the cell that created the vfile: make sure that the vfile
    # still exists
    await k.run([create_vfile_1])
    assert len(get_context().virtual_file_registry.registry) == 1

    # Create a new vfile, make sure we have two now
    await k.run([create_vfile_2 := exec_req.get("create_vfile(2)")])
    assert len(get_context().virtual_file_registry.registry) == 2

    # Remove the cells that create the vfiles
    await k.delete_cell(DeleteCellRequest(cell_id=create_vfile_1.cell_id))
    await k.delete_cell(DeleteCellRequest(cell_id=create_vfile_2.cell_id))

    # Reset the vfile cache
    await k.run([vfile_cache])


async def test_cell_deletion_clears_vfiles(
    execution_kernel: Kernel, exec_req: ExecReqProvider
) -> None:
    k = execution_kernel
    await k.run(
        [
            exec_req.get(
                """
                import io
                import marimo as mo
                import functools
                """
            ),
            vfile_cache := exec_req.get(
                """
                @functools.lru_cache()
                def create_vfile(arg):
                    del arg
                    bytestream = io.BytesIO(b"hello world")
                    return mo.pdf(bytestream)
                """
            ),
            exec_req.get("create_vfile(1)"),
        ]
    )
    assert len(get_context().virtual_file_registry.registry) == 1

    # Delete the vfile cache: virtual file registry should be empty
    await k.delete_cell(DeleteCellRequest(cell_id=vfile_cache.cell_id))
    assert len(get_context().virtual_file_registry.registry) == 0


async def test_vfile_refcount_incremented(
    execution_kernel: Kernel, exec_req: ExecReqProvider
) -> None:
    k = execution_kernel
    await k.run(
        [
            exec_req.get(
                """
                import io
                import marimo as mo
                import functools
                """
            ),
            exec_req.get(
                """
                @functools.lru_cache()
                def create_vfile(arg):
                    del arg
                    bytestream = io.BytesIO(b"hello world")
                    return mo.pdf(bytestream)
                """
            ),
            exec_req.get("md = mo.md(f'{create_vfile(1)}')"),
        ]
    )
    assert len(get_context().virtual_file_registry.registry) == 1
    vfile = list(get_context().virtual_file_registry.filenames())[0]

    #   1 reference for the cached `mo.pdf`
    # + 1 reference for the markdown
    # ---
    #   2 references
    assert get_context().virtual_file_registry.refcount(vfile) == 2


async def test_vfile_refcount_decremented(
    execution_kernel: Kernel, exec_req: ExecReqProvider
) -> None:
    k = execution_kernel
    await k.run(
        [
            exec_req.get(
                """
                import io
                import marimo as mo
                import gc
                """
            ),
            # no caching in this test
            exec_req.get(
                """
                def create_vfile(arg):
                    del arg
                    bytestream = io.BytesIO(b"hello world")
                    return mo.pdf(bytestream)
                """
            ),
            make_vfile := exec_req.get("mo.md(f'{create_vfile(1)}')"),
        ]
    )
    ctx = get_context()
    assert len(ctx.virtual_file_registry.registry) == 1
    vfile = list(ctx.virtual_file_registry.filenames())[0]

    # 0 references because HTML not bound to a variable
    # NB: this test may be flaky! refcount decremented when `__del__` is called
    # but we can't rely on when it will be called.
    await k.run([exec_req.get("gc.collect()")])
    assert ctx.virtual_file_registry.refcount(vfile) == 0

    # this should dispose the old vfile (because its refcount is 0) and create
    # a new one
    await k.run([make_vfile])
    # the previous vfile should not be in the registry
    assert vfile not in ctx.virtual_file_registry.registry
    assert len(ctx.virtual_file_registry.registry) == 1


async def test_cached_vfile_disposal(
    execution_kernel: Kernel, exec_req: ExecReqProvider
) -> None:
    k = execution_kernel
    await k.run(
        [
            exec_req.get(
                """
                import io
                import marimo as mo
                import functools
                import weakref
                """
            ),
            exec_req.get(
                """
                class namespace:
                  ...
                vfiles = namespace()
                vfiles.files = []
                ref = weakref.ref(vfiles)

                def create_vfile(arg):
                    del arg
                    bytestream = io.BytesIO(b"hello world")
                    return mo.pdf(bytestream)
                """
            ),
            append_vfile := exec_req.get(
                "ref().files.append(create_vfile(1))"
            ),
        ]
    )
    ctx = get_context()
    assert len(ctx.virtual_file_registry.registry) == 1
    vfile = list(ctx.virtual_file_registry.filenames())[0]

    # 1 reference, in the list
    assert ctx.virtual_file_registry.refcount(vfile) == 1

    # clear the list, refcount should be decremented
    await k.run([exec_req.get("ref().files[:] = []")])
    # NB: this test may be flaky! refcount decremented when `__del__` is called
    # but we can't rely on when it will be called.
    await k.run([exec_req.get("import gc; gc.collect()")])
    assert ctx.virtual_file_registry.refcount(vfile) == 0

    # create another vfile. the old one should be deleted
    await k.run([append_vfile])
    assert len(ctx.virtual_file_registry.registry) == 1
    assert vfile not in ctx.virtual_file_registry.filenames()


async def test_virtual_files_not_supported(
    execution_kernel: Kernel, exec_req: ExecReqProvider
) -> None:
    k = execution_kernel
    get_context().virtual_files_supported = False

    await k.run(
        [
            exec_req.get(
                """
                import io
                import marimo as mo
                bytestream = io.BytesIO(b"hello world")
                pdf_plugin = mo.pdf(bytestream)
                """
            ),
        ],
    )

    ctx = get_context()
    assert len(ctx.virtual_file_registry.registry) == 0
    ctx.virtual_files_supported = True

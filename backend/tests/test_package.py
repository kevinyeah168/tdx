def test_workbench_package_has_version() -> None:
    from workbench import __version__

    assert __version__ == "0.1.0"

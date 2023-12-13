from collections import namedtuple
from enum import Enum

import pytest

from leapp import reporting
from leapp.exceptions import StopActorExecutionError
from leapp.libraries.actor import checkrhui as checkrhui_lib
from leapp.libraries.common import rhsm, rhui
from leapp.libraries.common.config import mock_configs, version
from leapp.libraries.common.rhui import mk_rhui_setup, RHUIFamily
from leapp.libraries.common.testutils import create_report_mocked, CurrentActorMocked, produce_mocked
from leapp.libraries.stdlib import api
from leapp.models import (
    CopyFile,
    InstalledRPM,
    RequiredTargetUserspacePackages,
    RHUIInfo,
    RPM,
    RpmTransactionTasks,
    TargetRHUIPostInstallTasks,
    TargetRHUIPreInstallTasks,
    TargetRHUISetupInfo,
    TargetUserSpacePreupgradeTasks
)
from leapp.reporting import Report
from leapp.snactor.fixture import current_actor_context

RH_PACKAGER = 'Red Hat, Inc. <http://bugzilla.redhat.com/bugzilla>'


def mk_pkg(name):
    return RPM(name=name, version='0.1', release='1.sm01', epoch='1', packager=RH_PACKAGER, arch='noarch',
               pgpsig='RSA/SHA256, Mon 01 Jan 1970 00:00:00 AM -03, Key ID 199e2f91fd431d51')


def mk_setup_info():
    pre_tasks = TargetRHUIPreInstallTasks()
    post_tasks = TargetRHUIPostInstallTasks()
    return TargetRHUISetupInfo(preinstall_tasks=pre_tasks, postinstall_tasks=post_tasks)


def iter_known_rhui_setups():
    for upgrade_path, providers in rhui.RHUI_CLOUD_MAP.items():
        for provider_variant, variant_description in providers.items():
            src_clients = variant_description['src_pkg']
            if isinstance(src_clients, str):
                src_clients = {src_clients, }

            yield provider_variant, upgrade_path, src_clients


def mk_cloud_map(variants):
    upg_path = {}
    for variant_desc in variants:
        provider, desc = next(iter(variant_desc.items()))
        upg_path[provider] = desc
    return upg_path


@pytest.mark.parametrize(
    ('extra_pkgs', 'rhui_setups', 'expected_result'),
    [
        (
            ['client'],
            {RHUIFamily('provider'): [mk_rhui_setup(clients={'client'})]},
            RHUIFamily('provider')
        ),
        (
            ['client'],
            {RHUIFamily('provider'): [mk_rhui_setup(clients={'missing_client'})]},
            None
        ),
        (
            ['clientA', 'clientB'],
            {RHUIFamily('provider'): [mk_rhui_setup(clients={'clientB'})]},
            RHUIFamily('provider')
        ),
        (
            ['clientA', 'clientB'],
            {
                RHUIFamily('provider'): [mk_rhui_setup(clients={'clientA'})],
                RHUIFamily('provider+'): [mk_rhui_setup(clients={'clientA', 'clientB'})],
            },
            RHUIFamily('provider+')
        ),
        (
            ['client'],
            {
                RHUIFamily('providerA'): [mk_rhui_setup(clients={'client'})],
                RHUIFamily('providerB'): [mk_rhui_setup(clients={'client'})],
            },
            StopActorExecutionError
        ),
    ]
)
def test_determine_rhui_src_variant(monkeypatch, extra_pkgs, rhui_setups, expected_result):
    monkeypatch.setattr(api, 'current_actor', CurrentActorMocked(src_ver='7.9'))
    installed_pkgs = {'zip', 'zsh', 'bash', 'grubby'}.union(set(extra_pkgs))

    if expected_result and not isinstance(expected_result, RHUIFamily):  # An exception
        with pytest.raises(expected_result) as err:
            checkrhui_lib.find_rhui_setup_matching_src_system(installed_pkgs, rhui_setups)
        assert 'ambiguous' in str(err)
        return

    variant_setup_pair = checkrhui_lib.find_rhui_setup_matching_src_system(installed_pkgs, rhui_setups)
    if not expected_result:
        assert variant_setup_pair == expected_result
    else:
        variant = variant_setup_pair[0]
        assert variant == expected_result


@pytest.mark.parametrize(
    ('extra_pkgs', 'target_rhui_setup', 'should_inhibit'),
    [
        (['pkg'], mk_rhui_setup(leapp_pkg='pkg'), False),
        ([], mk_rhui_setup(leapp_pkg='pkg'), True),
    ]
)
def test_inhibit_on_missing_leapp_rhui_pkg(monkeypatch, extra_pkgs, target_rhui_setup, should_inhibit):
    installed_pkgs = set(['bash', 'zsh', 'zip'] + extra_pkgs)
    monkeypatch.setattr(reporting, 'create_report', create_report_mocked())
    checkrhui_lib.inhibit_if_leapp_pkg_to_access_target_missing(installed_pkgs,
                                                                RHUIFamily('rhui-variant'),
                                                                target_rhui_setup)
    assert bool(reporting.create_report.called) == should_inhibit


def are_setup_infos_eq(actual, expected):
    eq = True
    eq &= actual.enable_only_repoids_in_copied_files == expected.enable_only_repoids_in_copied_files
    eq &= actual.files_supporting_client_operation == expected.files_supporting_client_operation
    eq &= actual.preinstall_tasks.files_to_remove == expected.preinstall_tasks.files_to_remove
    eq &= actual.preinstall_tasks.files_to_copy_into_overlay == expected.preinstall_tasks.files_to_copy_into_overlay
    eq &= actual.postinstall_tasks.files_to_copy == expected.postinstall_tasks.files_to_copy
    return eq


@pytest.mark.parametrize(
    ('provider', 'should_mutate'),
    [
        (RHUIFamily(rhui.RHUIProvider.GOOGLE), True),
        (RHUIFamily(rhui.RHUIProvider.GOOGLE, variant=rhui.RHUIVariant.SAP), True),
        (RHUIFamily('azure'), False),
    ]
)
def test_google_specific_customization(provider, should_mutate):
    setup_info = mk_setup_info()
    checkrhui_lib.customize_rhui_setup_for_gcp(provider, setup_info)

    if should_mutate:
        assert setup_info != mk_setup_info()
    else:
        assert setup_info == mk_setup_info()


@pytest.mark.parametrize(
    ('rhui_family', 'target_major', 'should_mutate'),
    [
        (RHUIFamily(rhui.RHUIProvider.AWS), '8', False),
        (RHUIFamily(rhui.RHUIProvider.AWS), '9', True),
        (RHUIFamily(rhui.RHUIProvider.AWS, variant=rhui.RHUIVariant.SAP), '9', True),
        (RHUIFamily('azure'), '9', False),
    ]
)
def test_aws_specific_customization(monkeypatch, rhui_family, target_major, should_mutate):
    dst_ver = '{major}.0'.format(major=target_major)
    monkeypatch.setattr(api, 'current_actor', CurrentActorMocked(dst_ver=dst_ver))

    setup_info = mk_setup_info()
    checkrhui_lib.customize_rhui_setup_for_aws(rhui_family, setup_info)

    was_mutated = not are_setup_infos_eq(setup_info, mk_setup_info())
    assert should_mutate == was_mutated


def produce_rhui_info_to_setup_target(monkeypatch):
    source_rhui_setup = mk_rhui_setup(
        clients={'src_pkg'},
        leapp_pkg='leapp_pkg',
        mandatory_files=[('src_file1', '/etc'), ('src_file2', '/var')],
    )

    target_rhui_setup = mk_rhui_setup(
        clients={'target_pkg'},
        leapp_pkg='leapp_pkg',
        mandatory_files=[('target_file1', '/etc'), ('target_file2', '/var')],
    )

    monkeypatch.setattr(api, 'get_common_folder_path', lambda dummy: 'common_folder')
    monkeypatch.setattr(api, 'produce', produce_mocked())

    checkrhui_lib.produce_rhui_info_to_setup_target('provider', source_rhui_setup, target_rhui_setup)

    assert len(api.produce.model_instances) == 1

    rhui_info = api.produce.model_instances[0]
    assert rhui_info.provider == 'provider'
    assert rhui_info.src_client_pkg_names == ['src_pkg']
    assert rhui_info.target_client_pkg_names == ['target_pkg']

    setup_info = rhui_info.target_client_setup_info

    expected_copies = {
        ('common_folder/provider/target_file1', '/etc'),
        ('common_folder/provider/target_file2', '/var')
    }
    actual_copies = {(instr.src, instr.dst) for instr in setup_info.preinstall_tasks.files_to_copy_in}

    assert expected_copies == actual_copies

    assert not setup_info.postinstall_tasks.files_to_copy


def test_produce_rpms_to_install_into_target(monkeypatch):
    source_rhui_setup = mk_rhui_setup(clients={'src_pkg'}, leapp_pkg='leapp_pkg')
    target_rhui_setup = mk_rhui_setup(clients={'target_pkg'}, leapp_pkg='leapp_pkg')

    monkeypatch.setattr(api, 'produce', produce_mocked())

    checkrhui_lib.produce_rpms_to_install_into_target(source_rhui_setup, target_rhui_setup)

    assert len(api.produce.model_instances) == 2
    userspace_tasks, target_rpm_tasks = api.produce.model_instances[0], api.produce.model_instances[1]

    if isinstance(target_rpm_tasks, TargetUserSpacePreupgradeTasks):
        userspace_tasks, target_rpm_tasks = target_rpm_tasks, userspace_tasks

    assert 'target_pkg' in target_rpm_tasks.to_install
    assert 'src_pkg' in target_rpm_tasks.to_remove
    assert 'target_pkg' in userspace_tasks.install_rpms


@pytest.mark.parametrize('skip_rhsm', (True, False))
def test_inform_about_upgrade_with_rhui_without_no_rhsm(monkeypatch, skip_rhsm):
    monkeypatch.setattr(rhsm, 'skip_rhsm', lambda: skip_rhsm)
    monkeypatch.setattr(reporting, 'create_report', create_report_mocked())

    checkrhui_lib.inform_about_upgrade_with_rhui_without_no_rhsm()

    assert bool(reporting.create_report.called) is not skip_rhsm


class ExpectedAction(Enum):
    NOTHING = 1  # Actor should not produce anything
    INHIBIT = 2
    PRODUCE = 3  # Actor should produce RHUI related info


# Scenarios to cover:
# 1. source client + NO_RHSM -> RPMs are produced, and setup info is produced
# 2. source client -> inhibit
# 3. leapp pkg missing -> inhibit
@pytest.mark.parametrize(
    ('extra_installed_pkgs', 'skip_rhsm', 'expected_action'),
    [
        (['src_pkg', 'leapp_pkg'], True, ExpectedAction.PRODUCE),  # Everything OK
        (['src_pkg', 'leapp_pkg'], False, ExpectedAction.INHIBIT),  # No --no-rhsm
        (['src_pkg'], True, ExpectedAction.INHIBIT),  # Missing leapp-rhui package
        ([], True, ExpectedAction.NOTHING)  # Not a RHUI system
    ]
)
def test_process(monkeypatch, extra_installed_pkgs, skip_rhsm, expected_action):
    known_setups = {
        RHUIFamily('rhui-variant'): [
            mk_rhui_setup(clients={'src_pkg'}, os_version='7'),
            mk_rhui_setup(clients={'target_pkg'}, os_version='8', leapp_pkg='leapp_pkg',
                          mandatory_files=[('file1', '/etc'), ('file2', '/var')]),
        ]
    }

    installed_pkgs = {'zip', 'kernel-core', 'python'}.union(set(extra_installed_pkgs))
    installed_pkgs = [mk_pkg(pkg_name) for pkg_name in installed_pkgs]
    installed_rpms = InstalledRPM(items=installed_pkgs)

    monkeypatch.setattr(api, 'produce', produce_mocked())
    monkeypatch.setattr(api, 'current_actor', CurrentActorMocked(src_ver='7.9', msgs=[installed_rpms]))
    monkeypatch.setattr(reporting, 'create_report', create_report_mocked())
    monkeypatch.setattr(rhsm, 'skip_rhsm', lambda: skip_rhsm)
    monkeypatch.setattr(rhui, 'RHUI_SETUPS', known_setups)

    checkrhui_lib.process()

    if expected_action == ExpectedAction.NOTHING:
        assert not api.produce.called
        assert not reporting.create_report.called
    elif expected_action == ExpectedAction.INHIBIT:
        assert not api.produce.called
        assert len(reporting.create_report.reports) == 1
    else:  # expected_action = ExpectedAction.PRODUCE
        assert not reporting.create_report.called
        assert len(api.produce.model_instances) == 3
        assert any(isinstance(pkg, RpmTransactionTasks) for pkg in api.produce.model_instances)
        assert any(isinstance(pkg, RHUIInfo) for pkg in api.produce.model_instances)
        assert any(isinstance(pkg, TargetUserSpacePreupgradeTasks) for pkg in api.produce.model_instances)


@pytest.mark.parametrize('is_target_setup_known', (False, True))
def test_unknown_target_rhui_setup(monkeypatch, is_target_setup_known):
    rhui_family = RHUIFamily('rhui-variant')
    known_setups = {
        rhui_family: [
            mk_rhui_setup(clients={'src_pkg'}, os_version='7'),
        ]
    }

    if is_target_setup_known:
        target_setup = mk_rhui_setup(clients={'target_pkg'}, os_version='8', leapp_pkg='leapp_pkg')
        known_setups[rhui_family].append(target_setup)

    installed_pkgs = {'zip', 'kernel-core', 'python', 'src_pkg', 'leapp_pkg'}
    installed_pkgs = [mk_pkg(pkg_name) for pkg_name in installed_pkgs]
    installed_rpms = InstalledRPM(items=installed_pkgs)

    monkeypatch.setattr(api, 'produce', produce_mocked())
    monkeypatch.setattr(api, 'current_actor', CurrentActorMocked(src_ver='7.9', msgs=[installed_rpms]))
    monkeypatch.setattr(reporting, 'create_report', create_report_mocked())
    monkeypatch.setattr(rhsm, 'skip_rhsm', lambda: True)
    monkeypatch.setattr(rhui, 'RHUI_SETUPS', known_setups)

    if is_target_setup_known:
        checkrhui_lib.process()
        assert api.produce.called
    else:
        with pytest.raises(StopActorExecutionError):
            checkrhui_lib.process()

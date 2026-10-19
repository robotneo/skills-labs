"""Shared fail-closed privilege helper (dedup matrix, refactor 1).

``mor.check_privileges`` replaces six per-provider copies of the
currentSession + HasPrivilegeOnEntity check. Every "no positive evidence"
branch must still reject, and the single historical variant (clusters folding a
missing session into permission_denied/4) is preserved via overrides.
"""
import unittest

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere.mor import check_privileges


class NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def deny(exc, code, exit_code):
    return isinstance(exc, OperationError) and exc.code == code and exc.exit_code == exit_code


def content_with(check=None, session_key="sess-1"):
    session = NS(key=session_key) if session_key is not None else None
    manager = NS(HasPrivilegeOnEntity=check) if check is not None else NS()
    return NS(sessionManager=NS(currentSession=session), authorizationManager=manager)


class CheckPrivilegesTests(unittest.TestCase):
    REQUIRED = ("A.One", "B.Two")

    def test_all_true_passes(self):
        def check(*, entity, sessionId, privId):
            self.assertEqual(sessionId, "sess-1")
            self.assertEqual(list(privId), list(self.REQUIRED))
            return [True, True]
        check_privileges(content_with(check), object(), self.REQUIRED,
                         denied="d", unable="u")

    def test_missing_session_default_is_session_missing_3(self):
        content = content_with(check=lambda **k: [True, True], session_key=None)
        with self.assertRaises(OperationError) as ctx:
            check_privileges(content, object(), self.REQUIRED, denied="d", unable="u")
        self.assertTrue(deny(ctx.exception, "session_missing", 3))

    def test_blank_session_key_is_rejected(self):
        for bad in ("", None, 123):
            content = content_with(check=lambda **k: [True, True], session_key=bad)
            with self.assertRaises(OperationError) as ctx:
                check_privileges(content, object(), self.REQUIRED, denied="d", unable="u")
            self.assertTrue(deny(ctx.exception, "session_missing", 3), bad)

    def test_clusters_override_folds_missing_session_into_permission_denied_4(self):
        content = content_with(check=lambda **k: [True], session_key=None)
        with self.assertRaises(OperationError) as ctx:
            check_privileges(content, object(), ["X.Do"],
                             denied="denied", unable="unable",
                             session_code="permission_denied", session_exit=4,
                             session_message="unable")
        self.assertTrue(deny(ctx.exception, "permission_denied", 4))
        self.assertEqual(str(ctx.exception), "unable")

    def test_non_callable_check_is_permission_denied_4(self):
        content = NS(sessionManager=NS(currentSession=NS(key="s")),
                     authorizationManager=NS(HasPrivilegeOnEntity="not-callable"))
        with self.assertRaises(OperationError) as ctx:
            check_privileges(content, object(), self.REQUIRED,
                             denied="d", unable="无法核对权限")
        self.assertTrue(deny(ctx.exception, "permission_denied", 4))
        self.assertEqual(str(ctx.exception), "无法核对权限")

    def test_missing_authorization_manager_is_denied(self):
        content = NS(sessionManager=NS(currentSession=NS(key="s")))
        with self.assertRaises(OperationError) as ctx:
            check_privileges(content, object(), self.REQUIRED, denied="d", unable="u")
        self.assertTrue(deny(ctx.exception, "permission_denied", 4))

    def test_any_false_is_denied(self):
        def returns(granted):
            def check(**kw):
                return granted
            return check
        for granted in ([True, False], [False, True], [False, False]):
            content = content_with(check=returns(granted))
            with self.assertRaises(OperationError) as ctx:
                check_privileges(content, object(), self.REQUIRED,
                                 denied="账户缺少权限", unable="u")
            self.assertTrue(deny(ctx.exception, "permission_denied", 4), granted)
            self.assertEqual(str(ctx.exception), "账户缺少权限")

    def test_wrong_shape_or_count_is_denied(self):
        def returns(granted):
            def check(**kw):
                return granted
            return check
        for granted in (None, [True], [True, True, True], (True,), "yes", [1, 1]):
            content = content_with(check=returns(granted))
            with self.assertRaises(OperationError) as ctx:
                check_privileges(content, object(), self.REQUIRED, denied="d", unable="u")
            self.assertTrue(deny(ctx.exception, "permission_denied", 4), repr(granted))

    def test_truthy_non_true_values_are_not_accepted(self):
        # Strict identity: a non-bool truthy element is not positive proof.
        content = content_with(check=lambda **k: [True, 1])
        with self.assertRaises(OperationError) as ctx:
            check_privileges(content, object(), self.REQUIRED, denied="d", unable="u")
        self.assertTrue(deny(ctx.exception, "permission_denied", 4))

    def test_single_privilege_path(self):
        content = content_with(check=lambda **k: [True])
        check_privileges(content, object(), ("Host.Config.Maintenance",),
                         denied="d", unable="u")


if __name__ == "__main__":
    unittest.main()

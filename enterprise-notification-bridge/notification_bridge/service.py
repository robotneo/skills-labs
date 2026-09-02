from __future__ import absolute_import

import hashlib
import os
import platform as runtime_platform
import shutil
from collections.abc import Mapping

from .config import BridgeConfig, ConfigError
from .continuation import (
    ContinuationError,
    MemoryStateStore,
    create_action,
    normalize_capabilities,
    validate_capability_list,
    validate_operation_result,
)
from .contract import validate_envelope
from .dependencies import MINIMUM_DWS_VERSION, discover_dws, verify_dws
from .installer import plan_dws_install
from .ledger import Claim, DeliveryKey
from .models import Envelope
from .providers.base import ProviderResult
from .providers.native import NativeProvider
from .selector import select_provider


SUCCESS_STATUSES = frozenset((
    "ok", "sent", "delivered", "succeeded", "success",
))


class DeliveryBatchResult(object):
    def __init__(self, results):
        self.results = list(results)
        self.status = self._status()

    def _status(self):
        if not self.results:
            return "notification_disabled"
        if any(result.status == "failed" for result in self.results):
            return "notification_failed"
        if any(result.status in ("sent", "delivered", "succeeded", "success")
               for result in self.results):
            return "delivered"
        reasons = [result.reason for result in self.results if result.reason]
        if reasons and all(reason == reasons[0] for reason in reasons):
            return reasons[0]
        if any(result.status == "action_required" for result in self.results):
            return "action_required"
        return self.results[0].status


class BridgeService(object):
    def __init__(self, config, providers, ledger, state_store=None,
                 persist_config=None, dependency_discoverer=None,
                 dependency_verifier=None, dependency_installer=None,
                 dependency_plan=None, environment=None, platform_name=None,
                 which=None):
        self.config = config
        self.providers = list(providers)
        self.ledger = ledger
        self.state_store = state_store or MemoryStateStore()
        self._persist_config_callback = persist_config or (lambda: None)
        self._dependency_discoverer = dependency_discoverer or discover_dws
        self._dependency_verifier = dependency_verifier or verify_dws
        self._dependency_installer = dependency_installer
        self._dependency_plan = dependency_plan or plan_dws_install
        self._dependency_environment = dict(
            os.environ if environment is None else environment
        )
        self._dependency_platform = platform_name or runtime_platform.system()
        self._dependency_which = which or shutil.which

    def setup_dependency(self, platform, provider="auto", capabilities=None,
                         install_dws=False, china_mirror=False,
                         device_login=False, approved=False):
        """Prepare one notification dependency without selecting a recipient."""
        del device_login  # Reserved for the existing login continuation surface.
        capability_list = _capability_list(capabilities)
        if platform != "dingtalk":
            return ProviderResult("ready", "dws_dependency_not_applicable")
        if provider not in ("auto", "native", "dws-cli"):
            return ProviderResult("failed", "provider_unsupported")
        native_available = any(
            item["platform"] == platform for item in capability_list
        )
        if provider == "native":
            if not native_available:
                return ProviderResult("unavailable", "configured_provider_unavailable")
            return ProviderResult("ready", "native_provider_selected")
        if provider == "auto" and native_available:
            return ProviderResult("ready", "native_provider_selected")

        discovered = self._dependency_discoverer(
            self._dependency_environment, self._dependency_platform,
            self._dependency_which,
        )
        if discovered.status == "discovered":
            verified = self._dependency_verifier(
                discovered.executable, _runner_for_dependency(self.providers)
            )
        else:
            verified = discovered

        if verified.reason in ("dependency_install_required", "dws_upgrade_required"):
            if not install_dws or approved is not True:
                if install_dws:
                    return ProviderResult(
                        "action_required", "dependency_install_declined"
                    )
                return self._dependency_install_action(
                    platform, china_mirror, capability_list
                )
            if self._dependency_installer is None:
                return ProviderResult("failed", "dependency_install_failed")
            plan = self._dependency_plan(
                self._dependency_platform, china_mirror
            )
            installed = self._dependency_installer(plan, True)
            if installed.status != "ready":
                return ProviderResult(installed.status, installed.reason)
            discovered = self._dependency_discoverer(
                self._dependency_environment, self._dependency_platform,
                self._dependency_which,
            )
            if discovered.status != "discovered":
                return ProviderResult(discovered.status, discovered.reason)
            verified = self._dependency_verifier(
                discovered.executable, _runner_for_dependency(self.providers)
            )

        if verified.status != "ready":
            return ProviderResult(verified.status, verified.reason)

        self._inject_verified_dws(verified.executable)
        index, channel = self._ensure_setup_channel(platform, provider)
        selected = self._select(channel, capability_list)
        if getattr(selected, "availability", "available") == "unavailable":
            return ProviderResult("unavailable", selected.reason)
        return self._begin_authorization(
            None, capability_list, index, selected, "bind"
        ).results[0]

    def _dependency_install_action(self, platform, china_mirror, capabilities):
        data = {
            "minimum_version": MINIMUM_DWS_VERSION,
            "china_mirror": bool(china_mirror),
        }
        pending_actions = getattr(self.state_store, "pending_actions", None)
        if pending_actions is not None:
            for action in pending_actions():
                if (action.get("platform") == platform
                        and action.get("provider") == "dws-cli"
                        and action.get("operation") == "install_dependency"
                        and action.get("data") == data):
                    return ProviderResult(
                        "action_required", "dependency_install_required",
                        data={"action": action},
                    )
        report_id = hashlib.sha256(
            ("dependency:{0}:dws-cli".format(platform)).encode("utf-8")
        ).hexdigest()
        action = create_action(
            report_id, platform, "dws-cli", "install_dependency", data
        )
        self.state_store.save_pending(
            action, None, capabilities,
            _context("setup", "install_dependency", 0, 0, [], None,
                     False, platform, "dws-cli"),
        )
        return ProviderResult(
            "action_required", "dependency_install_required",
            data={"action": action},
        )

    def _inject_verified_dws(self, executable):
        for provider in self.providers:
            if provider.platform == "dingtalk" and provider.name == "dws-cli":
                if hasattr(provider, "executable"):
                    provider.executable = executable

    def _ensure_setup_channel(self, platform, provider):
        for index, channel in enumerate(self.config.channels):
            if channel.platform == platform:
                channel.provider = "dws-cli" if provider == "auto" else provider
                self._persist_config_callback()
                return index, channel
        from .config import ChannelConfig
        channel = ChannelConfig(
            platform, provider="dws-cli" if provider == "auto" else provider
        )
        self.config.channels.append(channel)
        self.config.enabled = True
        self._persist_config_callback()
        return len(self.config.channels) - 1, channel

    def deliver(self, envelope, capabilities=None, request_host_summary=False):
        self._validate_runtime_config()
        canonical = _canonical_envelope(envelope)
        capability_list = _capability_list(capabilities)
        if not isinstance(request_host_summary, bool):
            raise ContinuationError("summary request flag must be a boolean")
        self.state_store.save_retry(
            canonical.to_dict(), capability_list, request_host_summary
        )
        summary = canonical.ai_summary
        if (request_host_summary
                and (summary.get("mode") != "host_agent"
                     or not summary.get("text", "").strip())):
            result = self._suspend(
                canonical, capability_list, "deliver", 0, 0, [], None,
                "host", "host_agent", "summarize_report",
                {"report_json": canonical.report["json"]}, True,
            )
            return DeliveryBatchResult([result])
        result = self._run_delivery(canonical, capability_list, 0)
        return self._finalize(canonical.report_id, result)

    def retry(self, report_id, capabilities=None):
        record = self.state_store.load_retry(report_id)
        canonical = _envelope_from_dict(record["envelope"])
        capability_list = (
            _capability_list(capabilities) if capabilities is not None
            else validate_capability_list(record["capabilities"])
        )
        self.state_store.save_retry(
            canonical.to_dict(), capability_list,
            record["request_host_summary"],
        )
        result = self._run_delivery(canonical, capability_list, 0)
        return self._finalize(canonical.report_id, result)

    def bind(self, platform, capabilities=None):
        self._validate_runtime_config()
        channels = [
            (index, channel) for index, channel in enumerate(self.config.channels)
            if channel.platform == platform
        ]
        if not self.config.enabled or not channels:
            return ProviderResult("skipped", "platform_not_configured")
        index, channel = channels[0]
        capability_list = _capability_list(capabilities)
        provider = self._select(channel, capability_list)
        if getattr(provider, "availability", "available") == "unavailable":
            return ProviderResult("skipped", provider.reason)
        return self._begin_authorization(
            None, capability_list, index, provider, "bind"
        ).results[0]

    def continue_operation(self, operation_result):
        if not isinstance(operation_result, Mapping):
            raise ContinuationError("operation result must be an object")
        action_id = operation_result.get("action_id")
        record = self.state_store.load_pending(action_id)
        action = record["action"]
        result = validate_operation_result(dict(operation_result), action)
        context = record["context"]
        capabilities = validate_capability_list(record["capabilities"])
        envelope = (
            _envelope_from_dict(record["envelope"])
            if record["envelope"] is not None else None
        )
        self._validate_runtime_config()

        if result["status"] != "succeeded":
            batch = self._failed_continuation(
                action, result, envelope, capabilities, context
            )
            self.state_store.delete_pending(action_id)
            return self._finalize(
                envelope.report_id if envelope is not None else None, batch
            )

        stage = context["stage"]
        if stage == "summarize_report":
            prepared = envelope.with_ai_summary("host_agent", result["data"]["text"])
            self.state_store.save_retry(prepared.to_dict(), capabilities, False)
            batch = self._run_delivery(prepared, capabilities, 0)
        elif stage in ("auth_status", "auth_recheck"):
            batch = self._continue_authorization(
                envelope, capabilities, context, result["data"]["authorization"],
                recheck=(stage == "auth_recheck"),
            )
        elif stage == "login":
            batch = self._request_auth_status(
                envelope, capabilities, context["channel_index"],
                self._provider_for_context(context, capabilities),
                context["kind"], "auth_recheck",
            )
        elif stage == "list_profiles":
            batch = self._handle_profiles(
                envelope, capabilities, context["channel_index"],
                self._provider_for_context(context, capabilities),
                context["kind"], result["data"]["profiles"],
            )
        elif stage == "install_dependency":
            setup_result = self.setup_dependency(
                action["platform"], "dws-cli", {
                    "schema_version": "1", "capabilities": capabilities,
                }, install_dws=True,
                china_mirror=action["data"]["china_mirror"], approved=True,
            )
            batch = DeliveryBatchResult([setup_result])
        elif stage == "select_profile":
            selected = result["data"]["profile"]
            choices = [item["profile"] for item in action["data"]["profiles"]]
            if selected not in choices:
                raise ContinuationError("selected profile was not offered")
            provider = self._provider_for_context(context, capabilities)
            self._store_binding(context["channel_index"], provider, selected)
            if context["kind"] == "bind":
                batch = DeliveryBatchResult([
                    ProviderResult("ok", data={"profile": selected,
                                                "provider": provider.name})
                ])
            else:
                batch = self._after_profile(
                    envelope, capabilities, context["channel_index"], provider,
                    selected,
                )
        elif stage == "resolve_recipient":
            recipients = list(context["resolved_recipients"])
            recipients.append(result["data"]["recipient"])
            batch = self._resolve_recipients(
                envelope, capabilities, context["channel_index"],
                self._provider_for_context(context, capabilities),
                context["recipient_index"] + 1, recipients,
            )
        elif stage == "confirm_delivery":
            if not result["data"]["confirmed"]:
                batch = DeliveryBatchResult([
                    ProviderResult("skipped", "first_delivery_confirmation_required")
                ])
            else:
                provider = self._provider_for_context(context, capabilities)
                channel = self.config.channels[context["channel_index"]]
                scope = _confirmation_scope(
                    provider, channel.profile, context["resolved_recipients"]
                )
                self.state_store.confirm(scope)
                batch = self._send_recipients(
                    envelope, capabilities, context["channel_index"], provider,
                    context["recipient_index"], context["resolved_recipients"],
                )
        elif stage == "send_report":
            claim = _claim_from_context(context["claim"])
            if not self.ledger.mark_success(
                    claim, result["data"]["external_id"]):
                batch = DeliveryBatchResult([
                    ProviderResult("skipped", "stale_delivery_result")
                ])
            else:
                batch = self._with_following_recipients(
                    ProviderResult(
                        "sent", data={
                            "external_id": result["data"]["external_id"]
                        },
                    ), envelope, capabilities, context["channel_index"],
                    self._provider_for_context(context, capabilities),
                    context["recipient_index"] + 1,
                    context["resolved_recipients"],
                )
        elif stage == "delivery_status":
            batch = self._continue_reconciliation(
                envelope, capabilities, context, result["data"]
            )
        else:  # pragma: no cover - guarded by continuation schema
            raise ContinuationError("pending stage is unsupported")
        self.state_store.delete_pending(action_id)
        return self._finalize(
            envelope.report_id if envelope is not None else None, batch
        )

    def _run_delivery(self, envelope, capabilities, channel_index):
        channels = self.config.enabled_channels()
        if channel_index >= len(channels):
            return DeliveryBatchResult([])
        channel = channels[channel_index]
        provider = self._select(channel, capabilities)
        if getattr(provider, "availability", "available") == "unavailable":
            return self._with_following_channels(
                ProviderResult("skipped", provider.reason), envelope,
                capabilities, channel_index + 1,
            )
        return self._begin_authorization(
            envelope, capabilities, channel_index, provider, "deliver"
        )

    def _begin_authorization(self, envelope, capabilities, channel_index,
                             provider, kind):
        return self._request_auth_status(
            envelope, capabilities, channel_index, provider, kind,
            "auth_status",
        )

    def _request_auth_status(self, envelope, capabilities, channel_index,
                             provider, kind, stage):
        channel = self.config.channels[channel_index]
        try:
            result = provider.auth_status(channel.profile)
        except Exception:
            result = ProviderResult(
                "failed", "provider_auth_status_failed", retryable=True
            )
        if result.status == "action_required":
            return DeliveryBatchResult([self._suspend(
                envelope, capabilities, kind, channel_index, 0, [], None,
                provider.platform, provider.name, "auth_status",
                {"profile": channel.profile}, False, stage=stage,
            )])
        authorization = _authorization_state(result)
        if authorization == "failed":
            if kind == "deliver":
                return self._with_following_channels(
                    result, envelope, capabilities, channel_index + 1
                )
            return DeliveryBatchResult([result])
        return self._continue_authorization(
            envelope, capabilities,
            _context(
                kind, stage, channel_index, 0, [], None, False,
                provider.platform, provider.name,
            ),
            authorization, recheck=(stage == "auth_recheck"),
            provider=provider,
        )

    def _continue_authorization(self, envelope, capabilities, context,
                                authorization, recheck=False, provider=None):
        if provider is None:
            provider = self._provider_for_context(context, capabilities)
        if authorization == "authorized":
            return self._request_profiles(
                envelope, capabilities, context["channel_index"], provider,
                context["kind"],
            )
        if authorization in ("missing", "expired") and not recheck:
            try:
                result = provider.login()
            except Exception:
                result = ProviderResult(
                    "failed", "provider_login_failed", retryable=True
                )
            if result.status == "action_required":
                return DeliveryBatchResult([self._suspend(
                    envelope, capabilities, context["kind"],
                    context["channel_index"], 0, [], None,
                    provider.platform, provider.name, "login", {}, False,
                )])
            if result.status in SUCCESS_STATUSES or _authorization_state(result) == "authorized":
                return self._request_auth_status(
                    envelope, capabilities, context["channel_index"], provider,
                    context["kind"], "auth_recheck",
                )
            return DeliveryBatchResult([result])
        reason = ("authorization_recheck_failed" if recheck
                  else "authorization_required")
        return DeliveryBatchResult([
            ProviderResult("skipped", reason, retryable=authorization != "failed")
        ])

    def _request_profiles(self, envelope, capabilities, channel_index,
                          provider, kind):
        try:
            result = provider.list_profiles()
        except Exception:
            result = ProviderResult(
                "failed", "provider_profile_list_failed", retryable=True
            )
        if result.status == "action_required" and result.data.get("operation") == "list_profiles":
            return DeliveryBatchResult([self._suspend(
                envelope, capabilities, kind, channel_index, 0, [], None,
                provider.platform, provider.name, "list_profiles", {}, False,
            )])
        profiles = _profiles_from_result(result)
        if profiles is None:
            if (result.status == "action_required"
                    and result.reason == "profile_selection_required"):
                profiles = result.data.get("profiles")
            else:
                return DeliveryBatchResult([result])
        return self._handle_profiles(
            envelope, capabilities, channel_index, provider, kind, profiles
        )

    def _handle_profiles(self, envelope, capabilities, channel_index, provider,
                         kind, profiles):
        profiles = _normalize_profiles(profiles)
        channel = self.config.channels[channel_index]
        identifiers = [item["profile"] for item in profiles]
        if channel.profile is not None:
            if channel.profile not in identifiers:
                result = ProviderResult("skipped", "profile_not_validated")
                if kind == "deliver":
                    return self._with_following_channels(
                        result, envelope, capabilities, channel_index + 1
                    )
                return DeliveryBatchResult([result])
            self._store_binding(channel_index, provider, channel.profile)
            if kind == "bind":
                return DeliveryBatchResult([ProviderResult(
                    "ok", data={"profile": channel.profile,
                                "provider": provider.name}
                )])
            return self._after_profile(
                envelope, capabilities, channel_index, provider, channel.profile
            )
        if len(profiles) == 1:
            profile = profiles[0]["profile"]
            self._store_binding(channel_index, provider, profile)
            if kind == "bind":
                return DeliveryBatchResult([ProviderResult(
                    "ok", data={"profile": profile, "provider": provider.name}
                )])
            return self._after_profile(
                envelope, capabilities, channel_index, provider, profile
            )
        result = self._suspend(
            envelope, capabilities, kind, channel_index, 0, [], None,
            provider.platform, provider.name, "select_profile",
            {"profiles": profiles}, False,
        )
        return DeliveryBatchResult([result])

    def _after_profile(self, envelope, capabilities, channel_index, provider,
                       profile):
        channel = self.config.channels[channel_index]
        if not channel.recipients:
            return self._with_following_channels(
                ProviderResult("skipped", "recipient_not_configured"),
                envelope, capabilities, channel_index + 1,
            )
        return self._resolve_recipients(
            envelope, capabilities, channel_index, provider, 0, []
        )

    def _resolve_recipients(self, envelope, capabilities, channel_index,
                            provider, recipient_index, resolved_recipients):
        channel = self.config.channels[channel_index]
        if recipient_index >= len(channel.recipients):
            return self._confirm_or_send(
                envelope, capabilities, channel_index, provider,
                resolved_recipients,
            )
        selector = channel.recipients[recipient_index]
        try:
            result = provider.resolve_recipient(channel.profile, selector)
        except Exception:
            result = ProviderResult(
                "failed", "provider_recipient_resolution_failed", retryable=True
            )
        if result.status == "action_required" and result.data.get("operation") == "resolve_recipient":
            return DeliveryBatchResult([self._suspend(
                envelope, capabilities, "deliver", channel_index,
                recipient_index, resolved_recipients, None,
                provider.platform, provider.name, "resolve_recipient",
                {"profile": channel.profile, "selector": selector}, False,
            )])
        if result.status not in ("ok", "resolved"):
            return self._with_following_channels(
                result, envelope, capabilities, channel_index + 1
            )
        recipient = result.data.get("recipient")
        if not isinstance(recipient, str) or not recipient:
            return self._with_following_channels(
                ProviderResult("skipped", "recipient_not_resolved"), envelope,
                capabilities, channel_index + 1,
            )
        recipients = list(resolved_recipients) + [recipient]
        if len(recipients) != len(set(recipients)):
            return self._with_following_channels(
                ProviderResult("skipped", "duplicate_resolved_recipient"),
                envelope, capabilities, channel_index + 1,
            )
        return self._resolve_recipients(
            envelope, capabilities, channel_index, provider,
            recipient_index + 1, recipients,
        )

    def _confirm_or_send(self, envelope, capabilities, channel_index, provider,
                         recipients):
        channel = self.config.channels[channel_index]
        scope = _confirmation_scope(provider, channel.profile, recipients)
        if not self.state_store.is_confirmed(scope):
            return DeliveryBatchResult([self._suspend(
                envelope, capabilities, "deliver", channel_index, 0,
                recipients, None, provider.platform, provider.name,
                "confirm_delivery", {
                    "profile": channel.profile, "recipients": list(recipients),
                }, False,
            )])
        return self._send_recipients(
            envelope, capabilities, channel_index, provider, 0, recipients
        )

    def _send_recipients(self, envelope, capabilities, channel_index, provider,
                         recipient_index, recipients):
        if recipient_index >= len(recipients):
            return self._run_delivery(envelope, capabilities, channel_index + 1)
        channel = self.config.channels[channel_index]
        recipient = recipients[recipient_index]
        key = DeliveryKey(
            envelope.report_id, provider.platform, provider.name,
            channel.profile, recipient,
        )
        claim = self.ledger.claim(key)
        if not claim.acquired:
            if claim.reason == "delivery_reconciliation_required":
                try:
                    status = provider.delivery_status(
                        channel.profile, recipient, claim.claim_id
                    )
                except Exception:
                    status = ProviderResult(
                        "failed", "delivery_status_failed", retryable=True
                    )
                if (status.status == "action_required"
                        and status.data.get("operation") == "delivery_status"):
                    return DeliveryBatchResult([self._suspend(
                        envelope, capabilities, "deliver", channel_index,
                        recipient_index, recipients, claim,
                        provider.platform, provider.name, "delivery_status", {
                            "profile": channel.profile, "recipient": recipient,
                            "claim_id": claim.claim_id,
                        }, False,
                    )])
                return self._with_following_recipients(
                    ProviderResult("skipped", "delivery_reconciliation_required"),
                    envelope, capabilities, channel_index, provider,
                    recipient_index + 1, recipients,
                )
            return self._with_following_recipients(
                ProviderResult("skipped", claim.reason), envelope, capabilities,
                channel_index, provider, recipient_index + 1, recipients,
            )

        send_envelope = _canonical_envelope(envelope)
        validate_envelope(send_envelope)  # Integrity gate immediately before send.
        try:
            result = provider.send_report(
                channel.profile, recipient, send_envelope
            )
        except Exception:
            result = ProviderResult(
                "failed", "provider_send_failed", retryable=True
            )
        if result.status == "action_required" and result.data.get("operation") == "send_report":
            return DeliveryBatchResult([self._suspend(
                send_envelope, capabilities, "deliver", channel_index,
                recipient_index, recipients, claim,
                provider.platform, provider.name, "send_report", {
                    "profile": channel.profile, "recipient": recipient,
                    "envelope": send_envelope.to_dict(),
                    "claim_id": claim.claim_id,
                }, False,
            )])
        if result.status in SUCCESS_STATUSES:
            self.ledger.mark_success(
                claim, result.data.get("external_id", "")
            )
        else:
            self.ledger.mark_failure(
                claim, result.reason, bool(result.retryable)
            )
        return self._with_following_recipients(
            result, envelope, capabilities, channel_index, provider,
            recipient_index + 1, recipients,
        )

    def _continue_reconciliation(self, envelope, capabilities, context, data):
        claim = _claim_from_context(context["claim"])
        if data["delivery"] == "delivered":
            self.ledger.mark_success(claim, data["external_id"])
            return self._send_recipients(
                envelope, capabilities, context["channel_index"],
                self._provider_for_context(context, capabilities),
                context["recipient_index"] + 1,
                context["resolved_recipients"],
            )
        if data["delivery"] == "not_delivered":
            self.ledger.mark_failure(
                claim, "reconciled_not_delivered", retryable=True
            )
            return self._send_recipients(
                envelope, capabilities, context["channel_index"],
                self._provider_for_context(context, capabilities),
                context["recipient_index"], context["resolved_recipients"],
            )
        return DeliveryBatchResult([
            ProviderResult("skipped", "delivery_reconciliation_required")
        ])

    def _failed_continuation(self, action, result, envelope, capabilities,
                             context):
        reason = result["reason"] or "{0}_{1}".format(
            action["operation"], result["status"]
        )
        if context["stage"] == "summarize_report":
            prepared = envelope.with_ai_summary(
                "deterministic", deterministic_summary(envelope.report["json"])
            )
            self.state_store.save_retry(prepared.to_dict(), capabilities, False)
            return self._run_delivery(prepared, capabilities, 0)
        if context["stage"] == "send_report" and context["claim"] is not None:
            self.ledger.mark_failure(
                _claim_from_context(context["claim"]), reason,
                result["retryable"],
            )
        status = "failed" if result["status"] == "failed" else "skipped"
        return DeliveryBatchResult([
            ProviderResult(status, reason, result["retryable"])
        ])

    def _suspend(self, envelope, capabilities, kind, channel_index,
                 recipient_index, resolved_recipients, claim, platform,
                 provider, operation, data, request_host_summary, stage=None):
        report_id = (
            envelope.report_id if envelope is not None
            else hashlib.sha256(
                ("binding:" + platform).encode("utf-8")
            ).hexdigest()
        )
        action = create_action(
            report_id, platform, provider, operation, data
        )
        context = _context(
            kind, stage or operation, channel_index, recipient_index,
            resolved_recipients, claim, request_host_summary, platform,
            provider,
        )
        self.state_store.save_pending(
            action, envelope.to_dict() if envelope is not None else None,
            capabilities, context,
        )
        return ProviderResult(
            "action_required", "{0}_required".format(operation),
            data={"action": action},
        )

    def _select(self, channel, capabilities):
        return select_provider(
            channel.platform, channel.provider,
            self._providers_for(capabilities),
        )

    def _providers_for(self, capabilities):
        dynamic = [
            NativeProvider(item["platform"], item) for item in capabilities
        ]
        dynamic_keys = set((item.platform, item.name) for item in dynamic)
        base = [item for item in self.providers
                if (item.platform, item.name) not in dynamic_keys]
        return base + dynamic

    def _provider_for_context(self, context, capabilities):
        channel = self.config.channels[context["channel_index"]]
        provider = self._select(channel, capabilities)
        if getattr(provider, "availability", "available") == "unavailable":
            raise ContinuationError("pending provider is unavailable")
        if (provider.platform != context["platform"]
                or provider.name != context["provider"]):
            raise ContinuationError("pending provider identity changed")
        return provider

    def _store_binding(self, channel_index, provider, profile):
        channel = self.config.channels[channel_index]
        if (channel.provider not in ("auto", provider.name)
                or (channel.profile is not None and channel.profile != profile)):
            channel.recipients = []
        channel.provider = provider.name
        channel.profile = profile
        self._persist_config_callback()

    def _with_following_channels(self, result, envelope, capabilities,
                                 next_channel_index):
        following = self._run_delivery(
            envelope, capabilities, next_channel_index
        )
        return DeliveryBatchResult([result] + following.results)

    def _with_following_recipients(self, result, envelope, capabilities,
                                   channel_index, provider,
                                   next_recipient_index, recipients):
        following = self._send_recipients(
            envelope, capabilities, channel_index, provider,
            next_recipient_index, recipients,
        )
        return DeliveryBatchResult([result] + following.results)

    def _validate_runtime_config(self):
        try:
            BridgeConfig.from_dict(self.config.to_dict())
        except ConfigError:
            raise
        platforms = [channel.platform for channel in self.config.channels]
        if len(platforms) != len(set(platforms)):
            raise ConfigError("duplicate channel platform is not allowed")

    def _finalize(self, report_id, result):
        if report_id is not None and result.status == "delivered":
            self.state_store.delete_retry(report_id)
        return result


def deterministic_summary(report_json):
    diagnosis = report_json.get("diagnosis", {})
    parts = []
    verdict = diagnosis.get("verdict")
    if verdict is not None:
        parts.append("Wi-Fi health status: {0}.".format(verdict))
    score = diagnosis.get("score")
    if score is not None:
        parts.append("Score: {0}.".format(score))
    issues = [_summary_value(item) for item in diagnosis.get("issues", [])]
    issues = [item for item in issues if item]
    if issues:
        parts.append("Issues: {0}.".format(", ".join(issues)))
    recommendations = [
        _recommendation_value(item)
        for item in diagnosis.get("recommendations", [])
    ]
    recommendations = [item for item in recommendations if item]
    if recommendations:
        recommendation_text = "; ".join(recommendations)
        suffix = "" if recommendation_text.endswith((".", "!", "?")) else "."
        parts.append("Recommendations: {0}{1}".format(
            recommendation_text, suffix
        ))
    return " ".join(parts)


def _canonical_envelope(envelope):
    if not isinstance(envelope, Envelope):
        raise ValueError("envelope must be an Envelope")
    canonical = _envelope_from_dict(envelope.to_dict())
    validate_envelope(canonical)
    return canonical


def _envelope_from_dict(value):
    if not isinstance(value, Mapping):
        raise ContinuationError("stored envelope is invalid")
    required = set((
        "schema_version", "report_id", "generated_at", "detector", "report",
        "ai_summary",
    ))
    if set(value) != required:
        raise ContinuationError("stored envelope fields are invalid")
    envelope = Envelope(
        value["report_id"], value["generated_at"], value["detector"],
        value["report"], value["ai_summary"], value["schema_version"],
    )
    validate_envelope(envelope)
    return envelope


def _capability_list(value):
    return normalize_capabilities(value)


def _runner_for_dependency(providers):
    for provider in providers:
        if provider.platform == "dingtalk" and provider.name == "dws-cli":
            runner = getattr(provider, "_runner", None)
            if runner is not None:
                return runner
    return lambda unused: (1, "", "")


def _authorization_state(result):
    if result.status == "authorized":
        return "authorized"
    if result.status == "ok":
        if result.data.get("authenticated") is True:
            return "authorized"
        if result.data.get("authenticated") is False:
            return "missing"
    if result.status in ("missing", "expired", "unauthorized"):
        return "expired" if result.status == "expired" else "missing"
    if result.reason in ("login_required", "authorization_missing"):
        return "missing"
    if result.reason == "authorization_expired":
        return "expired"
    return "failed"


def _profiles_from_result(result):
    if result.status not in SUCCESS_STATUSES:
        return None
    if isinstance(result.data.get("profiles"), list):
        return result.data["profiles"]
    if isinstance(result.data.get("profile"), str):
        return [{"profile": result.data["profile"]}]
    return None


def _normalize_profiles(profiles):
    if not isinstance(profiles, list) or not profiles:
        raise ContinuationError("provider returned no valid profiles")
    normalized = []
    seen = set()
    for profile in profiles:
        if not isinstance(profile, Mapping):
            raise ContinuationError("provider profile is invalid")
        identifier = profile.get("profile")
        if not isinstance(identifier, str) or not identifier:
            raise ContinuationError("provider profile is invalid")
        if identifier in seen:
            raise ContinuationError("provider profiles are duplicated")
        seen.add(identifier)
        item = {"profile": identifier}
        display_name = profile.get("display_name")
        if isinstance(display_name, str) and display_name:
            item["display_name"] = display_name
        normalized.append(item)
    return normalized


def _context(kind, stage, channel_index, recipient_index,
             resolved_recipients, claim, request_host_summary, platform,
             provider):
    return {
        "kind": kind,
        "stage": stage,
        "channel_index": channel_index,
        "recipient_index": recipient_index,
        "resolved_recipients": list(resolved_recipients),
        "claim": _claim_dict(claim) if claim is not None else None,
        "request_host_summary": bool(request_host_summary),
        "platform": platform,
        "provider": provider,
    }


def _claim_dict(claim):
    return {
        "report_id": claim.key.report_id,
        "platform": claim.key.platform,
        "provider": claim.key.provider,
        "profile": claim.key.profile,
        "recipient": claim.key.recipient,
        "claim_id": claim.claim_id,
    }


def _claim_from_context(value):
    key = DeliveryKey(
        value["report_id"], value["platform"], value["provider"],
        value["profile"], value["recipient"],
    )
    return Claim(key, value["claim_id"], True, "")


def _confirmation_scope(provider, profile, recipients):
    return {
        "platform": provider.platform, "provider": provider.name,
        "profile": profile, "recipients": list(recipients),
    }


def _summary_value(value):
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def _recommendation_value(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return "" if value is None else str(value)
    for key in ("action", "recommendation", "text", "id"):
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
    return ""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from miy_api.core.asr_backend_registry import reset_asr_backends
from miy_api.core.llm_execution_adapters import (
    reset_llm_execution_adapters,
)
from miy_api.core.llm_model_profiles import (
    reset_llm_generation_profiles,
)
from miy_api.core.llm_pool_config_registry import (
    reset_llm_pool_config_resolvers,
)
from miy_api.core.llm_provider_registry import (
    reset_external_llm_providers,
)
from miy_api.core.settings import Settings
from miy_api.domains.ai.registry import (
    reset_ai_capability_registry,
)
from miy_api.domains.ai.runtime.external_adapters import (
    register_external_planner_execution_adapter,
    register_external_search_execution_adapter,
    reset_external_execution_adapters,
    select_external_planner_execution_adapter,
    select_external_search_execution_adapter,
    supported_external_planner_execution_adapters,
    supported_external_search_execution_adapters,
)
from miy_api.domains.ai.runtime.external_planner import ExternalPlannerExecutionResult
from miy_api.domains.ai.runtime.external_search import ExternalSearchExecutionResult
from miy_api.domains.conversations.scope_registry import (
    reset_conversation_scope_adapters,
)
from miy_api.domains.docs.app_catalog import DOCS_APP
from miy_api.domains.rag.source_adapter_registry import (
    reset_rag_source_adapters,
)
from miy_api.domains.retrieval.partition_adapter_registry import (
    reset_retrieval_partition_adapters,
)
from miy_api.domains.search.backend_factory import reset_keyword_search_backends
from miy_api.domains.search.entity_adapter_registry import (
    SearchEntityAdapter,
    SearchIndexLifecycleHooks,
    get_search_entity_adapter,
    register_search_entity_adapter,
    reset_search_entity_adapters,
)
from miy_api.domains.search.entity_registry import (
    reset_search_entity_descriptors,
)
from miy_api.domains.search.hook_registry import (
    register_search_index_hook,
    reset_search_index_hooks,
)
from miy_api.domains.search.projection_registry import (
    get_search_projection_adapter,
    reset_search_projection_adapters,
)
from miy_api.domains.search.resource_mapping import resource_type_for_search_entity
from miy_api.domains.source_access.registry import (
    reset_source_access_adapters,
)
from miy_api.domains.source_access.resource_types import (
    NATIVE_DOC_RESOURCE_TYPE,
)
from miy_api.domains.source_access.targets import (
    reset_target_access_adapters,
)
from miy_api.platform_extensions import (
    PlatformExtensionBootstrapError,
    initialize_platform_extensions,
    validate_platform_extension_registries,
)


def _reset_platform_registries() -> None:
    reset_ai_capability_registry()
    reset_asr_backends()
    reset_external_execution_adapters()
    reset_external_llm_providers()
    reset_llm_pool_config_resolvers()
    reset_llm_execution_adapters()
    reset_llm_generation_profiles()
    reset_conversation_scope_adapters()
    reset_rag_source_adapters()
    reset_retrieval_partition_adapters()
    reset_keyword_search_backends()
    reset_search_entity_adapters()
    reset_search_entity_descriptors()
    reset_search_index_hooks()
    reset_search_projection_adapters()
    reset_target_access_adapters()
    reset_source_access_adapters()


def _test_settings(**overrides) -> Settings:
    return Settings(
        MIY_POSTGRES_DSN=("postgresql+psycopg://miy_test:miy_test@127.0.0.1:5432/miy_test"),
        **overrides,
    )


def test_external_execution_adapter_registries_support_extension_factories() -> None:
    _reset_platform_registries()
    try:

        class VendorPlannerAdapter:
            adapter_id = "external_planner_v0"
            execution_provider = "vendor-planner"

            def execute(self, request):
                return ExternalPlannerExecutionResult(
                    status="completed",
                    execution_provider=self.execution_provider,
                    provider=request.provider,
                    planned_agent_ids=["docs.writer"],
                )

        class VendorSearchAdapter:
            adapter_id = "external_search_v0"
            execution_provider = "vendor-search"

            def execute(self, request):
                return ExternalSearchExecutionResult(
                    status="completed",
                    execution_provider=self.execution_provider,
                    provider=request.provider,
                    result_count=1,
                )

        register_external_planner_execution_adapter(
            "vendor-planner",
            VendorPlannerAdapter,
        )
        register_external_search_execution_adapter(
            "vendor-search",
            VendorSearchAdapter,
        )

        assert "vendor-planner" in supported_external_planner_execution_adapters()
        assert "vendor-search" in supported_external_search_execution_adapters()

        planner = select_external_planner_execution_adapter(
            SimpleNamespace(ai_external_planner_execution_adapter="vendor-planner"),
            execution_enabled=True,
        )
        search = select_external_search_execution_adapter(
            SimpleNamespace(ai_external_search_execution_adapter="vendor-search"),
            execution_enabled=True,
        )

        assert planner.execution_provider == "vendor-planner"
        assert search.execution_provider == "vendor-search"
    finally:
        _reset_platform_registries()


def test_platform_extension_validation_rejects_search_contract_owned_by_another_domain() -> None:
    _reset_platform_registries()
    try:
        initialize_platform_extensions(settings=_test_settings())

        def secret_company_loader(
            db,
        ):
            del db
            return []

        def secret_document_loader(db, *, entity_type, entity_id):
            del db, entity_type, entity_id
            return None

        def secret_index_hook():
            return None

        secret_company_loader.__module__ = "miy_api.domains.secret.search_projection"
        secret_document_loader.__module__ = "miy_api.domains.secret.search_projection"
        secret_index_hook.__module__ = "miy_api.domains.secret.search_hooks"

        hook_name = "secret.enqueue_record"
        register_search_index_hook(
            hook_name,
            secret_index_hook,
            owner_app=DOCS_APP,
            entity_type="secret_record",
            operations=("create", "update", "delete"),
        )
        register_search_entity_adapter(
            SearchEntityAdapter(
                owner_app=DOCS_APP,
                entity_type="secret_record",
                resource_type=NATIVE_DOC_RESOURCE_TYPE,
                label="Secret Record",
                label_key="ai.search.entitySecretRecord",
                company_loader=secret_company_loader,
                document_loader=secret_document_loader,
                index_hooks=SearchIndexLifecycleHooks(
                    create=(hook_name,),
                    update=(hook_name,),
                    delete=(hook_name,),
                ),
            )
        )

        with pytest.raises(PlatformExtensionBootstrapError) as exc_info:
            validate_platform_extension_registries(settings=_test_settings())

        message = str(exc_info.value)
        assert "secret_record loaders must belong to backend domain docs" in message
        assert "secret_record index hook callables must belong to their owner app domain" in message
    finally:
        _reset_platform_registries()


def test_search_entity_adapter_registers_descriptor_and_projection_atomically() -> None:
    _reset_platform_registries()
    try:
        adapter = SearchEntityAdapter(
            owner_app=DOCS_APP,
            entity_type="plugin_record",
            resource_type=NATIVE_DOC_RESOURCE_TYPE,
            label="Plugin Record",
            label_key="ai.search.entityPluginRecord",
            company_loader=lambda db,: [{"entity_id": "company-doc"}],
            document_loader=lambda db, *, entity_type, entity_id: {
                "entity_type": entity_type,
                "entity_id": entity_id,
            },
        )

        register_search_entity_adapter(adapter)

        assert get_search_entity_adapter("plugin_record") == adapter
        assert resource_type_for_search_entity("plugin_record") == NATIVE_DOC_RESOURCE_TYPE
        projection_adapter = get_search_projection_adapter("plugin_record")
        assert projection_adapter == adapter
        assert projection_adapter is not None
        assert projection_adapter.load_document(
            SimpleNamespace(),
            entity_type="plugin_record",
            entity_id="record-1",
        ) == {"entity_type": "plugin_record", "entity_id": "record-1"}
    finally:
        _reset_platform_registries()

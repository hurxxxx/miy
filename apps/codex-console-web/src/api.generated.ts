export interface paths {
    "/api/templates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listing */
        get: operations["listing_api_templates_get"];
        put?: never;
        /** Create */
        post: operations["create_api_templates_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/templates/{template_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read */
        get: operations["read_api_templates__template_id__get"];
        /** Edit */
        put: operations["edit_api_templates__template_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/templates/catalog": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Catalog */
        get: operations["catalog_api_templates_catalog_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/templates/{template_id}/run": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Run */
        post: operations["run_api_templates__template_id__run_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/registration": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Registration Status */
        get: operations["registration_status_api_tasks__task_id__registration_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/registration/authorize": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Registration Authorize */
        post: operations["registration_authorize_api_tasks__task_id__registration_authorize_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/registration/receipt": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Registration Receipt */
        post: operations["registration_receipt_api_tasks__task_id__registration_receipt_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/registration-authorizations/callback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Registration Callback */
        post: operations["registration_callback_api_registration_authorizations_callback_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/instructions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Listing */
        get: operations["listing_api_instructions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/instructions/document": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Document */
        get: operations["document_api_instructions_document_get"];
        /** Save */
        put: operations["save_api_instructions_document_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/catalog": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read Catalog */
        get: operations["read_catalog_api_workbench_catalog_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/apps/{app_id}/source": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Bind Source */
        put: operations["bind_source_api_workbench_apps__app_id__source_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/source-setup/options": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Source Setup Options */
        get: operations["source_setup_options_api_workbench_source_setup_options_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/projects/{project_id}/source-setup": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Source Setup Status */
        get: operations["source_setup_status_api_workbench_projects__project_id__source_setup_get"];
        put?: never;
        /** Source Setup Prepare */
        post: operations["source_setup_prepare_api_workbench_projects__project_id__source_setup_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/projects": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Project */
        post: operations["create_project_api_workbench_projects_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/projects/{project_id}/execution-readiness": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Project Execution Readiness */
        get: operations["project_execution_readiness_api_workbench_projects__project_id__execution_readiness_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/projects/{project_id}/registration-draft": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Registration Draft */
        get: operations["registration_draft_api_workbench_projects__project_id__registration_draft_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/projects/{project_id}/registration-status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Registration Status */
        get: operations["registration_status_api_workbench_projects__project_id__registration_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/runtime": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read Runtime */
        get: operations["read_runtime_api_workbench_runtime_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/apps/{app_id}/installations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Read Installations */
        get: operations["read_installations_api_workbench_apps__app_id__installations_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/apps/{app_id}/maintenance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Maintenance List */
        get: operations["maintenance_list_api_workbench_apps__app_id__maintenance_get"];
        put?: never;
        /** Create Maintenance */
        post: operations["create_maintenance_api_workbench_apps__app_id__maintenance_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/apps/{app_id}/maintenance/{record_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Maintenance */
        put: operations["update_maintenance_api_workbench_apps__app_id__maintenance__record_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/apps/{app_id}/maintenance/{record_id}/verify": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Verify Maintenance */
        post: operations["verify_maintenance_api_workbench_apps__app_id__maintenance__record_id__verify_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/apps/{app_id}/budget": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Budget */
        put: operations["budget_api_workbench_apps__app_id__budget_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/apps/{app_id}/usage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Usage */
        get: operations["usage_api_workbench_apps__app_id__usage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/workbench/platform": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Platform */
        get: operations["platform_api_workbench_platform_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/monitor/host": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Host Status */
        get: operations["host_status_api_monitor_host_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/monitor/services": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Service Status */
        get: operations["service_status_api_monitor_services_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/overview/{task_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Preferences */
        patch: operations["preferences_api_overview__task_id__patch"];
        trace?: never;
    };
    "/healthz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_healthz_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/session": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Session */
        get: operations["session_api_session_get"];
        put?: never;
        /** Login */
        post: operations["login_api_session_post"];
        /** Logout */
        delete: operations["logout_api_session_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/session/miy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Login From Miy */
        post: operations["login_from_miy_api_session_miy_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/codex/account": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Account */
        get: operations["account_api_codex_account_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/codex/models": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Models */
        get: operations["models_api_codex_models_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/codex/skills": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Discovered Skills */
        get: operations["discovered_skills_api_codex_skills_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/codex/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Codex Login */
        post: operations["codex_login_api_codex_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/codex/threads": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Threads */
        get: operations["threads_api_codex_threads_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Import Thread */
        post: operations["import_thread_api_tasks_import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Tasks */
        get: operations["tasks_api_tasks_get"];
        put?: never;
        /** New Task */
        post: operations["new_task_api_tasks_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Tasks */
        get: operations["tasks_api_overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/agents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Task Agents */
        get: operations["task_agents_api_tasks__task_id__agents_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/skills": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Task Skills */
        get: operations["task_skills_api_tasks__task_id__skills_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Task Detail */
        get: operations["task_detail_api_tasks__task_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/attachments/{attachment_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Upload Attachment */
        put: operations["upload_attachment_api_tasks__task_id__attachments__attachment_id__put"];
        post?: never;
        /** Delete Attachment */
        delete: operations["delete_attachment_api_tasks__task_id__attachments__attachment_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/attachments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Attachment List */
        get: operations["attachment_list_api_tasks__task_id__attachments_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/attachments/{attachment_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Download Attachment */
        get: operations["download_attachment_api_tasks__task_id__attachments__attachment_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/documents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Document */
        put: operations["document_api_tasks__task_id__documents_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/messages": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Message */
        post: operations["message_api_tasks__task_id__messages_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/implement": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Implement */
        post: operations["implement_api_tasks__task_id__implement_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/steer": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Steer */
        post: operations["steer_api_tasks__task_id__steer_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/interrupt": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Interrupt */
        post: operations["interrupt_api_tasks__task_id__interrupt_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/recover": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Recover */
        post: operations["recover_api_tasks__task_id__recover_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/requests/{request_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Answer */
        post: operations["answer_api_tasks__task_id__requests__request_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/changes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Changes */
        get: operations["changes_api_tasks__task_id__changes_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/git": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Git Status */
        get: operations["git_status_api_tasks__task_id__git_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/diff": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Diff */
        get: operations["diff_api_tasks__task_id__diff_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tasks/{task_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Events */
        get: operations["events_api_tasks__task_id__events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/overview/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Events */
        get: operations["events_api_overview_events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AccountOut */
        AccountOut: {
            /** Connected */
            connected: boolean;
            /** Auth Type */
            auth_type?: string | null;
            /** Plan Type */
            plan_type?: string | null;
            /** Rate Limits */
            rate_limits?: {
                [key: string]: unknown;
            } | null;
            /** Error Code */
            error_code?: string | null;
        };
        /** AgentOut */
        AgentOut: {
            /** Thread Id */
            thread_id: string;
            /** Parent Thread Id */
            parent_thread_id?: string | null;
            /** Name */
            name: string;
            /** Role */
            role?: string | null;
            /** Status */
            status: string;
            /**
             * Flags
             * @default []
             */
            flags: string[];
            /** Turn Id */
            turn_id?: string | null;
            /** Activity */
            activity?: string | null;
            /** Progress */
            progress?: {
                [key: string]: unknown;
            } | null;
            /** Updated At */
            updated_at: string;
            observation?: components["schemas"]["NativeObservationOut"] | null;
        };
        /** Answer */
        Answer: {
            /** Decision */
            decision?: ("accept" | "decline" | "cancel") | null;
            /** Answers */
            answers?: {
                [key: string]: string[];
            } | null;
        };
        /** AppDescriptor */
        AppDescriptor: {
            /** App Id */
            app_id: string;
            /** Title */
            title: string;
            /** Title Translations */
            title_translations?: {
                [key: string]: string;
            };
            /**
             * Icon Key
             * @default layout-grid
             */
            icon_key: string;
            /**
             * Summary
             * @default
             */
            summary: string;
            /** Capabilities */
            capabilities?: string[];
            /** Source Paths */
            source_paths?: string[];
            /** Release Unit */
            release_unit?: string | null;
            /** Route Base */
            route_base: string;
            /** Preview Url */
            preview_url?: string | null;
            /**
             * Source Status
             * @default unconfigured
             * @enum {string}
             */
            source_status: "ready" | "unconfigured" | "missing" | "invalid";
            /**
             * Discovery
             * @default checkout
             * @enum {string}
             */
            discovery: "checkout" | "runtime" | "source";
            /** Source Root */
            source_root?: string | null;
            /**
             * Source Version
             * @default 0
             */
            source_version: number;
            /**
             * Execution Status
             * @default unconfigured
             * @enum {string}
             */
            execution_status: "platform" | "configured" | "unconfigured";
            /**
             * Preview Status
             * @default unconfigured
             * @enum {string}
             */
            preview_status: "configured" | "unconfigured";
            /**
             * Deployment Status
             * @default unconfigured
             * @enum {string}
             */
            deployment_status: "configured" | "unconfigured";
            /** Limitations */
            limitations?: ("source_not_configured" | "source_missing" | "source_invalid" | "executor_not_configured" | "preview_not_configured" | "release_not_configured")[];
        };
        /** AttachmentLimits */
        AttachmentLimits: {
            /** File Bytes */
            file_bytes: number;
            /** Task Bytes */
            task_bytes: number;
            /** Files */
            files: number;
            /** Selection */
            selection: number;
        };
        /** AttachmentOut */
        AttachmentOut: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Size */
            size: number;
            /** Deleted */
            deleted: boolean;
        };
        /** AuthorizationStart */
        AuthorizationStart: {
            status: components["schemas"]["Status"];
            /** Authorization Url */
            authorization_url: string;
        };
        /** Begin */
        Begin: {
            /** Origin */
            origin: string;
        };
        /** BudgetInput */
        BudgetInput: {
            /** Development Tokens */
            development_tokens?: number | null;
            /** Runtime Tokens */
            runtime_tokens?: number | null;
            /** Amount Minor */
            amount_minor?: number | null;
            /**
             * Currency
             * @default KRW
             */
            currency: string;
            /**
             * Version
             * @default 0
             */
            version: number;
        };
        /** CatalogOut */
        CatalogOut: {
            /**
             * Registration Authorization Available
             * @default false
             */
            registration_authorization_available: boolean;
            /** Items */
            items: components["schemas"]["AppDescriptor"][];
            /** Projects */
            projects: components["schemas"]["ProjectOut"][];
            /** Source Revision */
            source_revision: string | null;
            /** Source Dirty */
            source_dirty: boolean;
            /**
             * Checked At
             * Format: date-time
             */
            checked_at: string;
        };
        /** ChangeOut */
        ChangeOut: {
            /** Path */
            path: string;
            /** Status */
            status: string;
            /** Old Path */
            old_path: string | null;
        };
        /** CommitOut */
        CommitOut: {
            /** Revision */
            revision: string;
            /** Subject */
            subject: string;
        };
        /** DeploymentObservation */
        DeploymentObservation: {
            /**
             * Request Id
             * Format: uuid
             */
            request_id: string;
            /**
             * Action
             * @enum {string}
             */
            action: "deploy" | "rollback";
            /**
             * State
             * @enum {string}
             */
            state: "queued" | "running" | "cleanup" | "succeeded" | "failed" | "unknown";
            /** Failure Code */
            failure_code?: string | null;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** DeviceLoginOut */
        DeviceLoginOut: {
            /** Login Id */
            login_id: string;
            /** Verification Url */
            verification_url: string;
            /** User Code */
            user_code: string;
        };
        /** DiffOut */
        DiffOut: {
            /** Path */
            path: string;
            /** Binary */
            binary: boolean;
            /** Old */
            old: string;
            /** New */
            new: string;
        };
        /** DiscoveredSkill */
        DiscoveredSkill: {
            /** Path */
            path: string;
            /** Name */
            name: string;
            /** Description */
            description: string;
            /** Enabled */
            enabled: boolean;
        };
        /** DiskOut */
        DiskOut: {
            /** Path */
            path: string;
            /** Total */
            total: number;
            /** Used */
            used: number;
            /** Available */
            available: number;
        };
        /** DocumentCatalog */
        DocumentCatalog: {
            /** Entries */
            entries: components["schemas"]["DocumentEntry"][];
            /** Roots */
            roots: {
                [key: string]: string;
            };
        };
        /** DocumentEntry */
        DocumentEntry: {
            /**
             * Scope
             * @enum {string}
             */
            scope: "project" | "personal" | "global" | "admin" | "system" | "plugins";
            /** Path */
            path: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "instructions" | "skill" | "metadata" | "reference" | "bridge" | "script";
            /** Editable */
            editable: boolean;
        };
        /** DocumentInput */
        DocumentInput: {
            /** Kind */
            kind?: "plan" | null;
            /** Base Version */
            base_version: number;
            /** Body */
            body: string;
        };
        /** DocumentOut */
        DocumentOut: {
            /**
             * Scope
             * @enum {string}
             */
            scope: "project" | "personal" | "global" | "admin" | "system" | "plugins";
            /** Path */
            path: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "instructions" | "skill" | "metadata" | "reference" | "bridge" | "script";
            /** Editable */
            editable: boolean;
            /** Exists */
            exists: boolean;
            /** Revision */
            revision: string | null;
            /** Content */
            content: string;
        };
        /** DocumentWrite */
        DocumentWrite: {
            /**
             * Scope
             * @enum {string}
             */
            scope: "project" | "personal" | "global" | "admin" | "system" | "plugins";
            /** Path */
            path: string;
            /** Content */
            content: string;
            /** Revision */
            revision?: string | null;
        };
        /** GitLabItem */
        GitLabItem: {
            /** Id */
            id?: number | null;
            /** Name */
            name: string;
            /** Revision */
            revision?: string | null;
            /** Status */
            status?: string | null;
            /** Url */
            url?: string | null;
        };
        /** GitLabOut */
        GitLabOut: {
            /** State */
            state: string;
            /** Checked At */
            checked_at?: string | null;
            /**
             * Stale
             * @default true
             */
            stale: boolean;
            /**
             * Branches
             * @default []
             */
            branches: components["schemas"]["GitLabItem"][];
            /**
             * Merge Requests
             * @default []
             */
            merge_requests: components["schemas"]["GitLabItem"][];
            /**
             * Pipelines
             * @default []
             */
            pipelines: components["schemas"]["GitLabItem"][];
        };
        /** GitStatusOut */
        GitStatusOut: {
            /** Root */
            root: string;
            /** Branch */
            branch: string | null;
            /** Head */
            head: string | null;
            /** Detached */
            detached: boolean;
            /** Upstream */
            upstream: string | null;
            /** Ahead */
            ahead: number | null;
            /** Behind */
            behind: number | null;
            /** Staged */
            staged: number;
            /** Unstaged */
            unstaged: number;
            /** Untracked */
            untracked: number;
            /** Conflicts */
            conflicts: number;
            /** Changed */
            changed: number;
            /** Checked At */
            checked_at: string;
        };
        /** GuidanceConfiguration */
        GuidanceConfiguration: {
            /** Fallback Filenames */
            fallback_filenames: string[];
            /** Max Bytes */
            max_bytes: number;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HostOut */
        HostOut: {
            /** Checked At */
            checked_at?: string | null;
            /**
             * Stale
             * @default true
             */
            stale: boolean;
            memory?: components["schemas"]["MemoryOut"] | null;
            /**
             * Disks
             * @default []
             */
            disks: components["schemas"]["DiskOut"][];
            /**
             * Load
             * @default []
             */
            load: number[];
            /** Cpu Count */
            cpu_count?: number | null;
            /** Installed Cli */
            installed_cli?: string | null;
            /** Template Cli */
            template_cli?: string | null;
            /**
             * Contract Cli
             * @default 0.159.2
             */
            contract_cli: string;
        };
        /** Implement */
        Implement: {
            /** Model */
            model?: string | null;
            /** Effort */
            effort?: string | null;
            /**
             * Permissions
             * @default ask
             * @enum {string}
             */
            permissions: "ask" | "yolo";
            /**
             * Operation Id
             * Format: uuid
             */
            operation_id: string;
            /** Revision Id */
            revision_id?: number | null;
            /**
             * Text
             * @default
             */
            text: string;
            /** Attachment Ids */
            attachment_ids?: string[];
            /** Skill Names */
            skill_names?: string[];
        };
        /** ImportThread */
        ImportThread: {
            /** Thread Id */
            thread_id: string;
            /**
             * Confirm Inactive
             * @constant
             */
            confirm_inactive: true;
        };
        /** InstallationObservation */
        InstallationObservation: {
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Environment
             * @enum {string}
             */
            environment: "development" | "production";
            /** Origin */
            origin: string;
            /** Enabled */
            enabled: boolean;
            /** State */
            state: string;
            /** Generation */
            generation: number;
            /** Release Id */
            release_id: string | null;
            /** Source Revision */
            source_revision?: string | null;
            /** Artifact Digest */
            artifact_digest?: string | null;
            deployment: components["schemas"]["DeploymentObservation"] | null;
            /**
             * Delivery Configured
             * @default false
             */
            delivery_configured: boolean;
        };
        /** InstallationsOut */
        InstallationsOut: {
            /**
             * State
             * @enum {string}
             */
            state: "ready" | "unconfigured" | "unavailable" | "unsupported" | "denied";
            /** Checked At */
            checked_at?: string | null;
            /**
             * Stale
             * @default true
             */
            stale: boolean;
            /**
             * Items
             * @default []
             */
            items: components["schemas"]["InstallationObservation"][];
        };
        /** LoginInput */
        LoginInput: {
            /** Password */
            password: string;
        };
        /** MIYSessionInput */
        MIYSessionInput: {
            /** Issuer */
            issuer: string;
            /** Code */
            code: string;
        };
        /** MaintenanceInput */
        MaintenanceInput: {
            /** Title */
            title: string;
            /**
             * Notes
             * @default
             */
            notes: string;
            /**
             * Owner
             * @default
             */
            owner: string;
            /** Due On */
            due_on?: string | null;
            /**
             * State
             * @default open
             * @enum {string}
             */
            state: "open" | "planned" | "cancelled";
            /** Target Revision */
            target_revision?: string | null;
            /** Task Id */
            task_id?: string | null;
            /**
             * Version
             * @default 0
             */
            version: number;
        };
        /** MaintenanceOut */
        MaintenanceOut: {
            /** Title */
            title: string;
            /**
             * Notes
             * @default
             */
            notes: string;
            /**
             * Owner
             * @default
             */
            owner: string;
            /** Due On */
            due_on?: string | null;
            /**
             * State
             * @enum {string}
             */
            state: "open" | "planned" | "cancelled" | "verified";
            /** Target Revision */
            target_revision?: string | null;
            /** Task Id */
            task_id?: string | null;
            /**
             * Version
             * @default 0
             */
            version: number;
            /** Id */
            id: string;
            /** App Id */
            app_id: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Verification */
            verification?: {
                [key: string]: unknown;
            } | null;
        };
        /** MemoryOut */
        MemoryOut: {
            /** Total */
            total: number;
            /** Used */
            used: number;
            /** Available */
            available: number;
            /** Swap Total */
            swap_total: number;
            /** Swap Used */
            swap_used: number;
            /** Cgroup Limit */
            cgroup_limit?: number | null;
            /** Cgroup Used */
            cgroup_used?: number | null;
        };
        /** Message */
        Message: {
            /** Model */
            model?: string | null;
            /** Effort */
            effort?: string | null;
            /**
             * Permissions
             * @default ask
             * @enum {string}
             */
            permissions: "ask" | "yolo";
            /**
             * Operation Id
             * Format: uuid
             */
            operation_id: string;
            /**
             * Text
             * @default
             */
            text: string;
            /**
             * Stage
             * @default plan
             * @constant
             */
            stage: "plan";
            /** Attachment Ids */
            attachment_ids?: string[];
            /** Skill Names */
            skill_names?: string[];
        };
        /** MessageBody */
        MessageBody: {
            /**
             * Operation Id
             * Format: uuid
             */
            operation_id: string;
            /**
             * Text
             * @default
             */
            text: string;
            /**
             * Stage
             * @default plan
             * @constant
             */
            stage: "plan";
            /** Attachment Ids */
            attachment_ids?: string[];
            /** Skill Names */
            skill_names?: string[];
        };
        /** ModelOut */
        ModelOut: {
            /** Model */
            model: string;
            /** Name */
            name: string;
            /** Is Default */
            is_default: boolean;
            /** Default Effort */
            default_effort: string;
            /** Efforts */
            efforts: string[];
        };
        /** NativeObservationOut */
        NativeObservationOut: {
            /** Thread Status */
            thread_status?: ("notLoaded" | "idle" | "active" | "systemError") | null;
            /** Thread Checked At */
            thread_checked_at?: string | null;
            last_turn?: components["schemas"]["NativeTurnObservation"] | null;
            /** Attempted At */
            attempted_at?: string | null;
            /** Error Code */
            error_code?: ("unavailable" | "read_failed" | "identity_mismatch") | null;
            /**
             * Freshness
             * @enum {string}
             */
            freshness: "fresh" | "stale" | "unavailable" | "unknown";
        };
        /** NativeTurnObservation */
        NativeTurnObservation: {
            /** Id */
            id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "inProgress" | "completed" | "interrupted" | "failed";
            /** Observed At */
            observed_at: string;
        };
        /** NewTask */
        NewTask: {
            /** Title */
            title: string;
            context?: components["schemas"]["TaskContext"] | null;
            /**
             * Isolate
             * @default false
             */
            isolate: boolean;
        };
        /** Ok */
        Ok: {
            /**
             * Ok
             * @default true
             */
            ok: boolean;
        };
        /** PlatformOut */
        PlatformOut: {
            git: components["schemas"]["GitStatusOut"] | null;
            /** Commits */
            commits: components["schemas"]["CommitOut"][];
            /** Worktrees */
            worktrees: string[];
            gitlab: components["schemas"]["GitLabOut"];
            workbench_release?: components["schemas"]["ReleaseIdentity"] | null;
        };
        /** Policy */
        Policy: {
            /** App Id */
            app_id: string;
            /** Origin */
            origin: string;
            /**
             * Runtime Profile
             * @enum {string}
             */
            runtime_profile: "web-api-v1" | "web-api-postgres-v1";
            /** Requested Permissions */
            requested_permissions: ("identity:read" | "data:read" | "data:write" | "files:read-selected")[];
        };
        /**
         * ProjectExecutionReadinessOut
         * @description Connection metadata at checked_at; not sandbox or Task authorization.
         */
        ProjectExecutionReadinessOut: {
            /** Project Id */
            project_id: string;
            /** App Id */
            app_id: string | null;
            /** Source Version */
            source_version: number | null;
            /**
             * State
             * @enum {string}
             */
            state: "reachable" | "unconfigured" | "unavailable" | "changed" | "unsupported" | "denied";
            /** Failure Code */
            failure_code: string | null;
            /**
             * Checked At
             * Format: date-time
             */
            checked_at: string;
        };
        /** ProjectInput */
        ProjectInput: {
            /** App Id */
            app_id: string;
            /** Title */
            title: string;
            /** Summary */
            summary: string;
            /**
             * Reuse Decision
             * @enum {string}
             */
            reuse_decision: "new" | "extend";
            /** Reuse Notes */
            reuse_notes: string;
        };
        /** ProjectOut */
        ProjectOut: {
            /** App Id */
            app_id: string;
            /** Title */
            title: string;
            /** Summary */
            summary: string;
            /**
             * Reuse Decision
             * @enum {string}
             */
            reuse_decision: "new" | "extend";
            /** Reuse Notes */
            reuse_notes: string;
            /** Id */
            id: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** Receipt */
        Receipt: {
            /**
             * Operation Id
             * Format: uuid
             */
            operation_id: string;
            /** App Id */
            app_id: string;
            /**
             * Installation Id
             * Format: uuid
             */
            installation_id: string;
            /** Definition Digest */
            definition_digest: string;
            /** Source Revision */
            source_revision: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** Recover */
        Recover: {
            /**
             * Confirm Workspace
             * @default false
             */
            confirm_workspace: boolean;
        };
        /** ReleaseIdentity */
        ReleaseIdentity: {
            /** Source Revision */
            source_revision: string;
            /** Source Dirty */
            source_dirty: boolean;
            /** Digest */
            digest: string;
        };
        /** RequestOut */
        RequestOut: {
            /** Id */
            id: string;
            /** Method */
            method: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
        };
        /** RevisionOut */
        RevisionOut: {
            /** Id */
            id: number;
            /** Kind */
            kind: string;
            /** Version */
            version: number;
            /** Body */
            body: string;
            /** Created At */
            created_at: string;
        };
        /** RuntimeApp */
        RuntimeApp: {
            /** App Id */
            app_id: string;
            /** Title */
            title: string;
            /** Enabled */
            enabled: boolean;
            /** Release Unit */
            release_unit?: string | null;
            /** Installed Revision */
            installed_revision?: string | null;
            /** Registered Source Revision */
            registered_source_revision?: string | null;
            /** Runtime Ai */
            runtime_ai: boolean;
            /** Title Translations */
            title_translations?: {
                [key: string]: string;
            };
            /**
             * Icon Key
             * @default layout-grid
             */
            icon_key: string;
            /** Source Repository */
            source_repository?: string | null;
            /** Source Directory */
            source_directory?: string | null;
            /** Definition Digest */
            definition_digest?: string | null;
        };
        /** RuntimeOut */
        RuntimeOut: {
            /**
             * State
             * @enum {string}
             */
            state: "ready" | "unconfigured" | "unavailable" | "unsupported" | "denied";
            /** Checked At */
            checked_at?: string | null;
            /**
             * Stale
             * @default true
             */
            stale: boolean;
            /**
             * Items
             * @default []
             */
            items: components["schemas"]["RuntimeApp"][];
            /** Catalog Revision */
            catalog_revision?: string | null;
            /** Registration Status Version */
            registration_status_version?: number | null;
        };
        /** RuntimeUsage */
        RuntimeUsage: {
            /**
             * Schema Version
             * @constant
             */
            schema_version: 1;
            /** App Id */
            app_id: string;
            /** Month */
            month: string;
            /** App Opens */
            app_opens: number;
            /** Llm Calls */
            llm_calls: number;
            /** Llm Errors */
            llm_errors: number;
            /** Total Tokens */
            total_tokens?: number | null;
            /** Unreported Calls */
            unreported_calls: number;
            /** Complete */
            complete: boolean;
            /** Amount Minor */
            amount_minor?: number | null;
            /** Currency */
            currency?: string | null;
            /**
             * Cost Basis
             * @enum {string}
             */
            cost_basis: "not_reported" | "reported";
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
        };
        /** ServiceOut */
        ServiceOut: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Environment */
            environment: string;
            /** Status */
            status: string;
            /** Version */
            version?: string | null;
            /** Checked At */
            checked_at?: string | null;
            /**
             * Stale
             * @default true
             */
            stale: boolean;
        };
        /** SessionOut */
        SessionOut: {
            /** Authenticated */
            authenticated: boolean;
        };
        /** SkillDiscovery */
        SkillDiscovery: {
            /** Directory */
            directory: string;
            /** Skills */
            skills: components["schemas"]["DiscoveredSkill"][];
            /** Error Count */
            error_count: number;
            guidance?: components["schemas"]["GuidanceConfiguration"] | null;
        };
        /** SkillOut */
        SkillOut: {
            /** Name */
            name: string;
            /** Description */
            description: string;
        };
        /** SourceBindingInput */
        SourceBindingInput: {
            /** Repository Root */
            repository_root: string;
            /**
             * Version
             * @default 0
             */
            version: number;
        };
        /** SourceCreationRoot */
        SourceCreationRoot: {
            /** Id */
            id: string;
            /** Label */
            label: string;
        };
        /** SourceRegistrationDraftOut */
        SourceRegistrationDraftOut: {
            /**
             * Schema Version
             * @default 1
             * @constant
             */
            schema_version: 1;
            /**
             * Project Id
             * Format: uuid
             */
            project_id: string;
            /** Binding Version */
            binding_version: number;
            /** App Id */
            app_id: string;
            /** Source Revision */
            source_revision: string;
            /** Source Manifest Digest */
            source_manifest_digest: string;
            /** Definition Digest */
            definition_digest: string;
            /** Definition */
            definition: {
                [key: string]: unknown;
            };
        };
        /** SourceRegistrationStatusOut */
        SourceRegistrationStatusOut: {
            /**
             * Project Id
             * Format: uuid
             */
            project_id: string;
            /** App Id */
            app_id: string;
            /** Binding Version */
            binding_version: number;
            /**
             * State
             * @enum {string}
             */
            state: "unregistered" | "matching" | "different" | "collision" | "unknown";
            /** Source Revision */
            source_revision: string;
            /** Definition Digest */
            definition_digest: string;
            /**
             * Platform State
             * @enum {string}
             */
            platform_state: "ready" | "unconfigured" | "unavailable" | "unsupported" | "denied";
            /** Platform Checked At */
            platform_checked_at: string | null;
            /** Registered Source Revision */
            registered_source_revision: string | null;
            /** Registered Definition Digest */
            registered_definition_digest: string | null;
            /** Definition Matches */
            definition_matches: boolean | null;
            /** Revision Matches */
            revision_matches: boolean | null;
        };
        /** SourceSetupInput */
        SourceSetupInput: {
            /**
             * Operation Id
             * Format: uuid
             */
            operation_id: string;
            /** Repository */
            repository: string;
            /** Root Id */
            root_id: string;
            /**
             * Template Id
             * @enum {string}
             */
            template_id: "basic" | "private-notes";
            /** Expected Bundle Digest */
            expected_bundle_digest: string;
        };
        /** SourceSetupOptions */
        SourceSetupOptions: {
            /** Roots */
            roots: components["schemas"]["SourceCreationRoot"][];
            /** Templates */
            templates: components["schemas"]["SourceStarter"][];
        };
        /** SourceSetupOut */
        SourceSetupOut: {
            /** Operation Id */
            operation_id: string;
            /** Project Id */
            project_id: string;
            /** App Id */
            app_id: string;
            /** Root Id */
            root_id: string;
            /**
             * Template Id
             * @enum {string}
             */
            template_id: "basic" | "private-notes";
            /** Repository */
            repository: string;
            /** Bundle Digest */
            bundle_digest: string;
            /**
             * State
             * @enum {string}
             */
            state: "preparing" | "ready" | "failed" | "conflict";
            /** Source Root */
            source_root: string | null;
            /** Source Revision */
            source_revision: string | null;
            /** Source Version */
            source_version: number | null;
            /** Failure Code */
            failure_code: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** SourceSetupStatus */
        SourceSetupStatus: {
            setup: components["schemas"]["SourceSetupOut"] | null;
        };
        /** SourceStarter */
        SourceStarter: {
            /**
             * Id
             * @enum {string}
             */
            id: "basic" | "private-notes";
            /** Name */
            name: string;
            /** Runtime Profile */
            runtime_profile: string;
            /** Bundle Digest */
            bundle_digest: string;
            /** Sdk Version */
            sdk_version: string;
        };
        /** Status */
        Status: {
            /**
             * Task Id
             * Format: uuid
             */
            task_id: string;
            /**
             * Operation Id
             * Format: uuid
             */
            operation_id: string;
            /** Enabled */
            enabled: boolean;
            /** Authorization Origin */
            authorization_origin: string | null;
            /**
             * Authorization State
             * @enum {string}
             */
            authorization_state: "required" | "pending" | "exchanging" | "ready" | "failed" | "expired" | "other_session";
            /**
             * State
             * @enum {string}
             */
            state: "unsubmitted" | "unknown" | "registered" | "rejected";
            /** Expires At */
            expires_at: string | null;
            policy: components["schemas"]["Policy"] | null;
            receipt: components["schemas"]["Receipt"] | null;
            /** Failure Code */
            failure_code: string | null;
            /** Source Revision */
            source_revision: string | null;
        };
        /** TaskContext */
        TaskContext: {
            /**
             * Purpose
             * @default development
             * @enum {string}
             */
            purpose: "development" | "inspection" | "deployment" | "recovery" | "registration";
            /** Service Id */
            service_id?: string | null;
            /** Area */
            area?: ("studio" | "apps" | "platform") | null;
            /** App Id */
            app_id?: string | null;
            /** Project Id */
            project_id?: string | null;
            /** Maintenance Id */
            maintenance_id?: string | null;
            /** Installation Id */
            installation_id?: string | null;
            /** Release Unit */
            release_unit?: string | null;
        };
        /** TaskDetail */
        TaskDetail: {
            /** Id */
            id: string;
            /** Title */
            title: string;
            /** Stage */
            stage: string;
            /** Status */
            status: string;
            /** Thread Id */
            thread_id: string | null;
            /** Turn Id */
            turn_id: string | null;
            /** Root */
            root: string;
            /** Isolated */
            isolated: boolean;
            /** Approved Revision */
            approved_revision: number | null;
            /** Error Code */
            error_code: string | null;
            /** Updated At */
            updated_at: string;
            /** Model */
            model?: string | null;
            /** Effort */
            effort?: string | null;
            /**
             * Permissions
             * @default read-only
             * @enum {string}
             */
            permissions: "read-only" | "ask" | "yolo";
            /** Progress */
            progress?: {
                [key: string]: unknown;
            } | null;
            /** Context */
            context?: {
                [key: string]: unknown;
            } | null;
            /**
             * Pinned
             * @default false
             */
            pinned: boolean;
            /**
             * Agents
             * @default []
             */
            agents: components["schemas"]["AgentOut"][];
            /**
             * Pending Count
             * @default 0
             */
            pending_count: number;
            /**
             * Executor
             * @default session
             * @enum {string}
             */
            executor: "session" | "templates";
            /** Template Snapshot */
            template_snapshot?: {
                [key: string]: unknown;
            } | null;
            /**
             * Implementation Permissions
             * @default [
             *       "ask",
             *       "yolo"
             *     ]
             */
            implementation_permissions: ("ask" | "yolo")[];
            /** Failed Request Text */
            failed_request_text?: string | null;
            /** Revisions */
            revisions: components["schemas"]["RevisionOut"][];
            /** Items */
            items: {
                [key: string]: unknown;
            }[];
            /** History Truncated */
            history_truncated: boolean;
            /** Requests */
            requests: components["schemas"]["RequestOut"][];
            /** Event Id */
            event_id: number;
            /** Attachments */
            attachments: components["schemas"]["AttachmentOut"][];
            attachment_limits: components["schemas"]["AttachmentLimits"];
        };
        /** TaskOut */
        TaskOut: {
            /** Id */
            id: string;
            /** Title */
            title: string;
            /** Stage */
            stage: string;
            /** Status */
            status: string;
            /** Thread Id */
            thread_id: string | null;
            /** Turn Id */
            turn_id: string | null;
            /** Root */
            root: string;
            /** Isolated */
            isolated: boolean;
            /** Approved Revision */
            approved_revision: number | null;
            /** Error Code */
            error_code: string | null;
            /** Updated At */
            updated_at: string;
            /** Model */
            model?: string | null;
            /** Effort */
            effort?: string | null;
            /**
             * Permissions
             * @default read-only
             * @enum {string}
             */
            permissions: "read-only" | "ask" | "yolo";
            /** Progress */
            progress?: {
                [key: string]: unknown;
            } | null;
            /** Context */
            context?: {
                [key: string]: unknown;
            } | null;
            /**
             * Pinned
             * @default false
             */
            pinned: boolean;
            /**
             * Agents
             * @default []
             */
            agents: components["schemas"]["AgentOut"][];
            /**
             * Pending Count
             * @default 0
             */
            pending_count: number;
            /**
             * Executor
             * @default session
             * @enum {string}
             */
            executor: "session" | "templates";
            /** Template Snapshot */
            template_snapshot?: {
                [key: string]: unknown;
            } | null;
        };
        /** TaskPreferences */
        TaskPreferences: {
            /** Pinned */
            pinned: boolean;
        };
        /** TemplateCatalog */
        TemplateCatalog: {
            /** Skills */
            skills: components["schemas"]["SkillOut"][];
            /** Models */
            models: components["schemas"]["ModelOut"][];
            /** Workspace */
            workspace: string;
        };
        /** TemplateDefinition */
        TemplateDefinition: {
            /** Name */
            name: string;
            /**
             * Description
             * @default
             */
            description: string;
            /** App Id */
            app_id?: string | null;
            /** Installation Id */
            installation_id?: string | null;
            /** Purpose */
            purpose?: ("inspection" | "deployment" | "recovery") | null;
            /**
             * Directory
             * @default .
             */
            directory: string;
            /**
             * Context
             * @default
             */
            context: string;
            /** References */
            references?: string[];
            /** Skills */
            skills?: string[];
            /** Prompt */
            prompt: string;
            /** Variables */
            variables?: components["schemas"]["TemplateVariable"][];
            /**
             * Stage
             * @default implement
             * @enum {string}
             */
            stage: "plan" | "implement";
            /**
             * Permissions
             * @default ask
             * @enum {string}
             */
            permissions: "ask" | "yolo";
            /**
             * Isolate
             * @default false
             */
            isolate: boolean;
            /**
             * Shared Resources
             * @default true
             */
            shared_resources: boolean;
            /** Model */
            model?: string | null;
            /** Effort */
            effort?: string | null;
        };
        /** TemplateOut */
        TemplateOut: {
            /** Id */
            id: string;
            /** Version */
            version: number;
            definition: components["schemas"]["TemplateDefinition"];
            /** Archived */
            archived: boolean;
            /** Updated At */
            updated_at: string;
        };
        /** TemplateRun */
        TemplateRun: {
            /**
             * Launch Id
             * Format: uuid
             */
            launch_id: string;
            /** Version */
            version: number;
            /** Values */
            values?: {
                [key: string]: string;
            };
        };
        /** TemplateUpdate */
        TemplateUpdate: {
            /** Version */
            version: number;
            definition: components["schemas"]["TemplateDefinition"];
            /**
             * Archived
             * @default false
             */
            archived: boolean;
        };
        /** TemplateVariable */
        TemplateVariable: {
            /** Name */
            name: string;
            /** Label */
            label: string;
            /**
             * Default
             * @default
             */
            default: string;
            /**
             * Required
             * @default true
             */
            required: boolean;
        };
        /** ThreadPage */
        ThreadPage: {
            /** Items */
            items: components["schemas"]["ThreadSummary"][];
            /** Cursor */
            cursor: string | null;
        };
        /** ThreadSummary */
        ThreadSummary: {
            /** Id */
            id: string;
            /** Title */
            title: string;
            /** Preview */
            preview: string;
            /** Updated At */
            updated_at: number;
        };
        /** UsageOut */
        UsageOut: {
            /** Month */
            month: string;
            /** Development Tokens */
            development_tokens: number | null;
            /** Development Tasks */
            development_tasks: number;
            /** Unreported Tasks */
            unreported_tasks: number;
            /** Development Amount Minor */
            development_amount_minor?: null;
            runtime?: components["schemas"]["RuntimeUsage"] | null;
            /** Runtime State */
            runtime_state: string;
            /** Runtime Checked At */
            runtime_checked_at?: string | null;
            /**
             * Stale
             * @default true
             */
            stale: boolean;
            budget: components["schemas"]["BudgetInput"];
            /** Alerts */
            alerts: string[];
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
        /** VerifyMaintenance */
        VerifyMaintenance: {
            /** Version */
            version: number;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    listing_api_templates_get: {
        parameters: {
            query?: {
                archived?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TemplateOut"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_api_templates_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TemplateDefinition"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TemplateOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_api_templates__template_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TemplateOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    edit_api_templates__template_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TemplateUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TemplateOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    catalog_api_templates_catalog_get: {
        parameters: {
            query?: {
                directory_name?: string;
                app_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TemplateCatalog"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    run_api_templates__template_id__run_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                template_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TemplateRun"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    registration_status_api_tasks__task_id__registration_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Status"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    registration_authorize_api_tasks__task_id__registration_authorize_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Begin"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuthorizationStart"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    registration_receipt_api_tasks__task_id__registration_receipt_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Status"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    registration_callback_api_registration_authorizations_callback_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    listing_api_instructions_get: {
        parameters: {
            query?: {
                scope?: ("project" | "personal" | "global" | "admin" | "system" | "plugins") | null;
                q?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocumentCatalog"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    document_api_instructions_document_get: {
        parameters: {
            query: {
                scope: "project" | "personal" | "global" | "admin" | "system" | "plugins";
                path: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocumentOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    save_api_instructions_document_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DocumentWrite"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocumentOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_catalog_api_workbench_catalog_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CatalogOut"];
                };
            };
        };
    };
    bind_source_api_workbench_apps__app_id__source_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SourceBindingInput"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppDescriptor"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    source_setup_options_api_workbench_source_setup_options_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceSetupOptions"];
                };
            };
        };
    };
    source_setup_status_api_workbench_projects__project_id__source_setup_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceSetupStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    source_setup_prepare_api_workbench_projects__project_id__source_setup_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SourceSetupInput"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceSetupOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_project_api_workbench_projects_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProjectInput"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    project_execution_readiness_api_workbench_projects__project_id__execution_readiness_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectExecutionReadinessOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    registration_draft_api_workbench_projects__project_id__registration_draft_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceRegistrationDraftOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    registration_status_api_workbench_projects__project_id__registration_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                project_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceRegistrationStatusOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_runtime_api_workbench_runtime_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RuntimeOut"];
                };
            };
        };
    };
    read_installations_api_workbench_apps__app_id__installations_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InstallationsOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    maintenance_list_api_workbench_apps__app_id__maintenance_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MaintenanceOut"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_maintenance_api_workbench_apps__app_id__maintenance_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MaintenanceInput"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MaintenanceOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_maintenance_api_workbench_apps__app_id__maintenance__record_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_id: string;
                record_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MaintenanceInput"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MaintenanceOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    verify_maintenance_api_workbench_apps__app_id__maintenance__record_id__verify_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_id: string;
                record_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VerifyMaintenance"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MaintenanceOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    budget_api_workbench_apps__app_id__budget_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BudgetInput"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BudgetInput"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    usage_api_workbench_apps__app_id__usage_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                app_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UsageOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    platform_api_workbench_platform_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlatformOut"];
                };
            };
        };
    };
    host_status_api_monitor_host_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HostOut"];
                };
            };
        };
    };
    service_status_api_monitor_services_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ServiceOut"][];
                };
            };
        };
    };
    preferences_api_overview__task_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TaskPreferences"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Ok"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_healthz_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Ok"];
                };
            };
        };
    };
    session_api_session_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionOut"];
                };
            };
        };
    };
    login_api_session_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginInput"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    logout_api_session_delete: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Ok"];
                };
            };
        };
    };
    login_from_miy_api_session_miy_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MIYSessionInput"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    account_api_codex_account_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccountOut"];
                };
            };
        };
    };
    models_api_codex_models_get: {
        parameters: {
            query?: {
                task_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModelOut"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    discovered_skills_api_codex_skills_get: {
        parameters: {
            query?: {
                directory_name?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SkillDiscovery"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    codex_login_api_codex_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeviceLoginOut"];
                };
            };
        };
    };
    threads_api_codex_threads_get: {
        parameters: {
            query?: {
                search?: string;
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadPage"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    import_thread_api_tasks_import_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ImportThread"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    tasks_api_tasks_get: {
        parameters: {
            query?: {
                search?: string;
                template_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskOut"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    new_task_api_tasks_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NewTask"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    tasks_api_overview_get: {
        parameters: {
            query?: {
                search?: string;
                template_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskOut"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    task_agents_api_tasks__task_id__agents_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentOut"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    task_skills_api_tasks__task_id__skills_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SkillOut"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    task_detail_api_tasks__task_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_attachment_api_tasks__task_id__attachments__attachment_id__put: {
        parameters: {
            query?: never;
            header: {
                "x-file-name": string;
            };
            path: {
                task_id: string;
                attachment_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/octet-stream": string;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AttachmentOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_attachment_api_tasks__task_id__attachments__attachment_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
                attachment_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Ok"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    attachment_list_api_tasks__task_id__attachments_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AttachmentOut"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_attachment_api_tasks__task_id__attachments__attachment_id__download_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
                attachment_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    document_api_tasks__task_id__documents_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DocumentInput"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    message_api_tasks__task_id__messages_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Message"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    implement_api_tasks__task_id__implement_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Implement"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    steer_api_tasks__task_id__steer_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MessageBody"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    interrupt_api_tasks__task_id__interrupt_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Ok"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    recover_api_tasks__task_id__recover_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Recover"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    answer_api_tasks__task_id__requests__request_id__post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
                request_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Answer"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaskDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    changes_api_tasks__task_id__changes_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ChangeOut"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    git_status_api_tasks__task_id__git_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GitStatusOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    diff_api_tasks__task_id__diff_get: {
        parameters: {
            query: {
                path: string;
            };
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DiffOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    events_api_tasks__task_id__events_get: {
        parameters: {
            query?: {
                after?: number;
            };
            header?: never;
            path: {
                task_id: string | null;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    events_api_overview_events_get: {
        parameters: {
            query?: {
                task_id?: string | null;
                after?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}

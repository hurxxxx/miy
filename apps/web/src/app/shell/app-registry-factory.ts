import {
  createCoreAppModuleRegistry,
  createCoreAppModuleRegistryApi,
  type CoreAppModuleRegistration,
  type CoreAppModuleRegistry,
} from '@miy/core-web/app-registry';
import type { ComponentType, ReactNode } from 'react';

import type { BackgroundWorkSource } from '@/src/platform/background-work/background-work-session';
import type {
  AppBarItem,
  AppModuleId,
  AppModuleManifest,
  AppShellNavResolver,
  NavItem,
  StaticRouteDefinition,
} from './navigation-types';
import type {
  AppRouteDefinition,
  ToolViewRouteDefinition,
} from './route-types';
import type { AppSidebarConfig } from './sidebar-types';

export type ShellProviderComponent = ComponentType<{ children: ReactNode }>;

export type AppModuleRegistration = CoreAppModuleRegistration<
  AppModuleId,
  NavItem,
  AppModuleManifest,
  StaticRouteDefinition,
  AppRouteDefinition,
  ToolViewRouteDefinition,
  BackgroundWorkSource,
  AppSidebarConfig,
  AppShellNavResolver,
  ShellProviderComponent
>;

export type AppModuleRegistry = CoreAppModuleRegistry<
  AppModuleId,
  NavItem,
  AppModuleManifest,
  AppBarItem,
  StaticRouteDefinition,
  AppRouteDefinition,
  ToolViewRouteDefinition,
  BackgroundWorkSource,
  AppSidebarConfig,
  AppShellNavResolver,
  ShellProviderComponent
>;

type AppModuleRegistryInput = AppModuleManifest | AppModuleRegistration;

export function createAppModuleRegistry(
  manifests: readonly AppModuleManifest[],
): AppModuleRegistry;
export function createAppModuleRegistry(
  registrations: readonly AppModuleRegistration[],
): AppModuleRegistry;
export function createAppModuleRegistry(
  inputs: readonly AppModuleRegistryInput[],
): AppModuleRegistry {
  return createCoreAppModuleRegistry<
    AppModuleId,
    NavItem,
    AppModuleManifest,
    AppBarItem,
    StaticRouteDefinition,
    AppRouteDefinition,
    ToolViewRouteDefinition,
    BackgroundWorkSource,
    AppSidebarConfig,
    AppShellNavResolver,
    ShellProviderComponent
  >(inputs);
}

export function createAppModuleRegistryApi(
  inputs: readonly AppModuleRegistryInput[],
) {
  return createCoreAppModuleRegistryApi<
    AppModuleId,
    NavItem,
    AppModuleManifest,
    AppBarItem,
    StaticRouteDefinition,
    AppRouteDefinition,
    ToolViewRouteDefinition,
    BackgroundWorkSource,
    AppSidebarConfig,
    AppShellNavResolver,
    ShellProviderComponent
  >(inputs);
}

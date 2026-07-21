# frontend-design-system Specification

## Purpose

Define the shared design foundation of the frontend: design tokens as the single source of visual
values, app-wide light/dark theming with a persisted toggle, overflow-safe rendering of long
identifiers, shared loading/empty-state treatments, and a shared toast notification mechanism. These
foundations are consumed by the chat and review surfaces so the app reads as one consistent, themeable
system.

## Requirements

### Requirement: Design tokens are the single source of visual values
The frontend SHALL define its visual values — color, spacing, radius, typographic scale, and shadow — as design tokens (CSS custom properties, provided via Open Props) referenced by component styles, rather than as hardcoded literals. Component styles SHALL reference tokens (`var(--…)`) so that changing a token propagates app-wide.

#### Scenario: Components reference tokens, not literals
- **WHEN** a component needs a color, spacing, or radius value
- **THEN** it references a design token rather than a hardcoded hex/length literal, so the value is consistent with the rest of the app and changeable in one place

#### Scenario: No orphaned hardcoded colors remain in redesigned surfaces
- **WHEN** the chat and review surfaces are rendered after the token adoption
- **THEN** their colors derive from tokens (no bare `#ccc`/`#b00020`/`rgba(0,0,0,…)` literals driving themeable surfaces), so dark mode renders correctly

### Requirement: App-wide light/dark theming with a persisted toggle
The frontend SHALL support light and dark themes built on the design tokens, applied across all three surfaces, with a user-facing toggle (light / dark / follow-system) whose selection persists across reloads. The default SHALL follow the operating-system preference.

#### Scenario: System preference is followed by default
- **WHEN** a user with no saved preference loads the app under an OS dark-mode setting
- **THEN** the app renders in the dark theme

#### Scenario: Explicit choice persists across reload
- **WHEN** the user selects the light (or dark) theme and reloads the page
- **THEN** the app renders in the chosen theme rather than reverting to the system default

### Requirement: Long identifiers render overflow-safe
Any surface that renders a raw identifier (IRI, URN, or unit code) SHALL render it so that a long value wraps or is otherwise contained within its box and does not force horizontal overflow of its container or sibling content.

#### Scenario: A long IRI does not break the layout
- **WHEN** a surface renders a long identifier such as `http://qudt.org/vocab/unit/MOL-PER-KiloGM` or a full `urn:msr:proposal:…` id
- **THEN** the identifier wraps/contains within its box and the surrounding layout is not pushed wider than the viewport

### Requirement: Shared loading and empty states
The frontend SHALL provide shared loading and empty-state treatments (e.g. a skeleton/spinner while a fetch is in flight, and a meaningful message when a list has no items) used by the surfaces, so a pending or empty view reads as intentional rather than broken or blank.

#### Scenario: In-flight fetch shows a loading state
- **WHEN** a surface is waiting on a fetch to resolve
- **THEN** it shows a loading affordance rather than a blank area

#### Scenario: Empty list shows a meaningful message
- **WHEN** a list (e.g. the proposal queue) resolves to zero items
- **THEN** the surface shows an explanatory empty state rather than an empty container

### Requirement: Toast notifications for actions
The frontend SHALL provide a shared, non-blocking toast notification mechanism for reporting the outcome of user actions (success or failure), announced to assistive technology via a live region, and dismissed automatically or by the user.

#### Scenario: Successful action shows a toast
- **WHEN** a user action (such as approving a proposal or creating a checkpoint) succeeds
- **THEN** a non-blocking toast confirms the outcome and is announced via an `aria-live`/`role=status` region

#### Scenario: Toast does not block interaction
- **WHEN** a toast is visible
- **THEN** the user can continue interacting with the surface and the toast dismisses itself or on user action

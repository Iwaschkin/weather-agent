"""Reflex configuration for the drone-flyability dashboard."""

import reflex as rx

config = rx.Config(
    app_name="weather_dashboard",
    plugins=[
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(
                appearance="dark",
                accent_color="cyan",
                radius="large",
                scaling="100%",
            ),
        ),
    ],
    disable_plugins=[rx.plugins.SitemapPlugin],
)

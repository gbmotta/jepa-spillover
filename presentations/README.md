# Apresentações

`slides.md` está em formato **[Marp](https://marp.app/)** (Markdown → slides).

## Como gerar

```bash
# Instale o Marp CLI (uma vez)
npm install -g @marp-team/marp-cli

# Exportar para PDF
marp presentations/slides.md --pdf --allow-local-files

# Exportar para HTML
marp presentations/slides.md --html --allow-local-files

# Exportar para PPTX (PowerPoint)
marp presentations/slides.md --pptx --allow-local-files
```

Alternativa: instale a extensão **Marp for VS Code** e use o preview/exportação direto no editor.

> Os diagramas referenciados (Mermaid) estão em `docs/flowcharts/`. Para incorporá-los como imagem
> nos slides, exporte-os via Mermaid CLI (`mmdc`) ou cole as renderizações do GitHub.

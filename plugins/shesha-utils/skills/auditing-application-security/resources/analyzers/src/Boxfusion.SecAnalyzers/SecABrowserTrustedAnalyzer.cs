using System.Collections.Generic;
using System.Collections.Immutable;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Diagnostics;

namespace Boxfusion.SecAnalyzers
{
    /// <summary>
    /// SEC-A — access decided by what the browser sends (BOLA / param-trust).
    ///
    /// PREDICATE (determinism-standard.md §2, deterministic boolean): a public method of
    /// an app-service / controller type has a Guid/Guid? parameter whose name is an
    /// actor-id (<see cref="Predicates.IsActorIdName"/>), that parameter flows into a
    /// read/scope decision, AND the method body has no server-side session cross-check
    /// (<see cref="Predicates.SessionCrossCheckNames"/>). One finding per method.
    /// </summary>
    [DiagnosticAnalyzer(LanguageNames.CSharp)]
    public sealed class SecABrowserTrustedAnalyzer : DiagnosticAnalyzer
    {
        // Roslyn requires a DiagnosticId that is a valid identifier (no hyphen); the driver
        // maps '_' → '-' to recover the determinism-standard check id "SEC-A".
        public const string Id = "SEC_A";

        private static readonly DiagnosticDescriptor Rule = new DiagnosticDescriptor(
            id: Id,
            title: "Access decided by a client-supplied entity id (browser-trusted flow)",
            messageFormat: "'{0}' uses browser-supplied id '{1}' as the actor/scope with no server-side session cross-check",
            category: "Security",
            defaultSeverity: DiagnosticSeverity.Warning,
            isEnabledByDefault: true,
            description: "The actor's scope must be derived on the server from AbpSession/GetLoggedInPersonAsync, not from a request parameter.");

        public override ImmutableArray<DiagnosticDescriptor> SupportedDiagnostics => ImmutableArray.Create(Rule);

        public override void Initialize(AnalysisContext context)
        {
            context.ConfigureGeneratedCodeAnalysis(GeneratedCodeAnalysisFlags.None);
            context.EnableConcurrentExecution();
            context.RegisterSyntaxNodeAction(AnalyzeMethod, SyntaxKind.MethodDeclaration);
        }

        private static void AnalyzeMethod(SyntaxNodeAnalysisContext ctx)
        {
            var decl = (MethodDeclarationSyntax)ctx.Node;
            if (decl.Body == null && decl.ExpressionBody == null) return;

            var model = ctx.SemanticModel;
            if (model.GetDeclaredSymbol(decl) is not IMethodSymbol method) return;

            // Reachable surface: public, instance, on an app-service / controller type.
            if (method.DeclaredAccessibility != Accessibility.Public) return;
            if (method.IsStatic) return;
            if (!IsReachableServiceType(method.ContainingType)) return;

            // Actor-id Guid parameters.
            var actorParams = method.Parameters
                .Where(p => IsGuid(p.Type) && Predicates.IsActorIdName(p.Name.ToLowerInvariant()))
                .ToImmutableArray();
            if (actorParams.Length == 0) return;

            // Body with no server-side cross-check of the actor.
            SyntaxNode body = (SyntaxNode?)decl.Body ?? decl.ExpressionBody!;
            if (HasSessionCrossCheck(body)) return;

            // At least one actor param must flow into a read/scope decision.
            IParameterSymbol? flowing = null;
            foreach (var p in actorParams)
            {
                if (FlowsIntoReadOrScope(p, decl, model)) { flowing = p; break; }
            }
            if (flowing == null) return;

            var props = ImmutableDictionary<string, string?>.Empty
                .Add(AnchorHelper.AnchorKey, AnchorHelper.MemberFragment(method))
                .Add(AnchorHelper.PathKey, decl.SyntaxTree.FilePath);

            ctx.ReportDiagnostic(Diagnostic.Create(
                Rule, decl.Identifier.GetLocation(), props,
                method.ContainingType.Name + "." + method.Name, flowing.Name));
        }

        private static bool IsGuid(ITypeSymbol t)
        {
            if (t is INamedTypeSymbol n && n.OriginalDefinition.SpecialType == SpecialType.System_Nullable_T)
                t = n.TypeArguments[0];
            return t.Name == "Guid" && t.ContainingNamespace?.ToString() == "System";
        }

        private static bool IsReachableServiceType(INamedTypeSymbol type)
        {
            // Only genuine HTTP surfaces: ABP ApplicationService (every *AppService /
            // Crud base derives from it) and MVC/ABP controllers. DomainService-derived
            // managers are NOT externally reachable — the browser-trusted decision lives
            // at the app-service boundary that calls them, so they are excluded.
            for (var t = type; t != null; t = t.BaseType)
            {
                var n = t.Name;
                if (n == "ApplicationService" || n == "AbpController" ||
                    n == "ControllerBase" || n == "Controller")
                    return true;
            }
            // Name fallback for an unresolved framework base symbol.
            return type.Name.EndsWith("AppService") || type.Name.EndsWith("Controller");
        }

        private static bool HasSessionCrossCheck(SyntaxNode body)
        {
            foreach (var id in body.DescendantNodes().OfType<SimpleNameSyntax>())
            {
                if (Predicates.SessionCrossCheckNames.Contains(id.Identifier.ValueText))
                    return true;
            }
            return false;
        }

        /// <summary>
        /// The parameter flows into a read/scope decision iff it is (a) an argument to a
        /// repository/LINQ query method, or (b) an operand of an ==/!= filter against an
        /// entity '…Id' member (excluding Guid.Empty/null/default validity guards).
        /// </summary>
        private static bool FlowsIntoReadOrScope(IParameterSymbol p, MethodDeclarationSyntax decl, SemanticModel model)
        {
            foreach (var idn in decl.DescendantNodes().OfType<IdentifierNameSyntax>())
            {
                if (idn.Identifier.ValueText != p.Name) continue;
                if (model.GetSymbolInfo(idn).Symbol is not IParameterSymbol sym) continue;
                if (!SymbolEqualityComparer.Default.Equals(sym, p)) continue;

                // (a) argument to a query method (directly, or inside a lambda argument).
                if (IsQueryMethodArgument(idn)) return true;

                // (b) ==/!= filter against an entity id member.
                if (IsEntityIdComparison(idn)) return true;
            }
            return false;
        }

        private static bool IsQueryMethodArgument(SyntaxNode node)
        {
            for (var n = node.Parent; n != null; n = n.Parent)
            {
                if (n is ArgumentSyntax arg && arg.Parent is ArgumentListSyntax al &&
                    al.Parent is InvocationExpressionSyntax inv)
                {
                    if (NameOf(inv.Expression) is string name && Predicates.QueryMethodNames.Contains(name))
                        return true;
                }
                // stop climbing once we pass a statement boundary that isn't an expression
                if (n is StatementSyntax && n is not ExpressionStatementSyntax && n is not ReturnStatementSyntax &&
                    n is not LocalDeclarationStatementSyntax)
                    break;
            }
            return false;
        }

        private static bool IsEntityIdComparison(SyntaxNode node)
        {
            for (var n = node.Parent; n != null; n = n.Parent)
            {
                if (n is BinaryExpressionSyntax be &&
                    (be.IsKind(SyntaxKind.EqualsExpression) || be.IsKind(SyntaxKind.NotEqualsExpression)))
                {
                    var other = be.Left == node || be.Left.DescendantNodesAndSelf().Contains(node) ? be.Right : be.Left;
                    if (IsValidityGuard(other)) return false; // Guid.Empty/null/default guard — not a scope decision
                    if (IsIdMemberAccess(other)) return true;
                    // comparison against another local/param that is itself an id member handled by the id-member side
                    return IsIdMemberAccess(be.Left) || IsIdMemberAccess(be.Right);
                }
                if (n is LambdaExpressionSyntax) continue; // comparisons live inside Where/First lambdas
                if (n is StatementSyntax) break;
            }
            return false;
        }

        private static bool IsValidityGuard(ExpressionSyntax e)
        {
            var s = e.ToString();
            return s == "Guid.Empty" || s == "System.Guid.Empty" || s.EndsWith(".Empty") ||
                   e.IsKind(SyntaxKind.NullLiteralExpression) || e is DefaultExpressionSyntax ||
                   e.IsKind(SyntaxKind.DefaultLiteralExpression);
        }

        private static bool IsIdMemberAccess(ExpressionSyntax e)
        {
            if (e is MemberAccessExpressionSyntax ma)
            {
                var name = ma.Name.Identifier.ValueText;
                return name == "Id" || name.EndsWith("Id");
            }
            return false;
        }

        private static string? NameOf(ExpressionSyntax expr) => expr switch
        {
            MemberAccessExpressionSyntax ma => ma.Name.Identifier.ValueText,
            IdentifierNameSyntax id => id.Identifier.ValueText,
            GenericNameSyntax gn => gn.Identifier.ValueText,
            MemberBindingExpressionSyntax mb => mb.Name.Identifier.ValueText,
            _ => null,
        };
    }
}

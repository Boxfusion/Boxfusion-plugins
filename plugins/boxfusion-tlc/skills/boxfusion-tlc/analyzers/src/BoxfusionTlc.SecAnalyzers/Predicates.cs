using System;
using System.Collections.Immutable;

namespace BoxfusionTlc.SecAnalyzers
{
    /// <summary>
    /// Frozen, closed token sets shared by the two analyzers. Everything here is a
    /// compile-time constant so two runs on the same commit evaluate the identical
    /// predicate (operating-standard.md §2/§9 — no sampling, no judgement).
    /// </summary>
    internal static class Predicates
    {
        // SEC-A: a Guid parameter is an "actor id" iff its name ends in "id" and
        // contains one of these tokens. Closed set (checks/security.md SEC-A INPUT +
        // the R2/R4 pins). Case-insensitive compare on the lower-cased name.
        internal static readonly ImmutableArray<string> ActorIdTokens = ImmutableArray.Create(
            "person", "profile", "owner", "user", "employee", "appointment", "farmer", "delegat");

        // Audit ids are explicitly excluded (checks/security.md SEC-A: "exclude
        // creatorUserId|lastModifierUserId|deleterUserId").
        internal static readonly ImmutableArray<string> AuditIdNames = ImmutableArray.Create(
            "creatoruserid", "lastmodifieruserid", "deleteruserid", "creationuserid", "modifieruserid");

        // SEC-A dataflow sink: the parameter is used as a read/scope key when it is an
        // argument to one of these repository/LINQ query methods.
        internal static readonly ImmutableHashSet<string> QueryMethodNames = ImmutableHashSet.Create(
            StringComparer.Ordinal,
            "GetAsync", "Get", "GetAllAsync", "GetAll", "GetAllListAsync", "GetAllList",
            "FirstOrDefaultAsync", "FirstOrDefault", "FirstAsync", "First",
            "SingleOrDefaultAsync", "SingleOrDefault", "SingleAsync", "Single",
            "AnyAsync", "Any", "CountAsync", "Count", "Where", "Query",
            "Load", "LoadAsync", "ToListAsync");

        // SEC-A: a server-side re-derivation of the actor. If ANY of these names appear
        // in the method body the actor is (at least attempted to be) resolved from the
        // session/principal, so the method is NOT a browser-trusted flow.
        internal static readonly ImmutableHashSet<string> SessionCrossCheckNames = ImmutableHashSet.Create(
            StringComparer.Ordinal,
            "AbpSession", "GetLoggedInPersonAsync", "GetLoggedInPerson",
            "GetLoggedInUserAsync", "GetCurrentPersonAsync", "GetCurrentPerson",
            "GetCurrentUserAsync", "GetCurrentUser", "CurrentUser");

        // SEC-H: logger method names (closed). A call qualifies as a log/trace site only
        // when its method name is one of these AND the receiver is logger-like.
        internal static readonly ImmutableHashSet<string> LogMethodNames = ImmutableHashSet.Create(
            StringComparer.Ordinal,
            "Log", "LogInformation", "LogInfo", "LogDebug", "LogWarning", "LogWarn",
            "LogError", "LogTrace", "LogCritical", "LogFatal",
            "Info", "Information", "Debug", "Warn", "Warning", "Error", "Trace", "Fatal", "Critical");

        // SEC-H: identifier names that mark the receiver as a logger when the type is an
        // unresolved/framework symbol.
        internal static readonly ImmutableHashSet<string> LoggerReceiverNames = ImmutableHashSet.Create(
            StringComparer.OrdinalIgnoreCase, "logger", "_logger", "log", "_log");

        // SEC-H: POPIA PII property tokens (frozen — checks/security.md R6 line 72 /
        // R8 line 79). Matched case-insensitively against the member's simple name.
        internal static readonly ImmutableHashSet<string> PiiPropertyTokens = ImmutableHashSet.Create(
            StringComparer.OrdinalIgnoreCase,
            "IdentityNumber", "PersalNo", "PersalNumber", "FullName", "DateOfBirth", "LeaveReason");

        /// <summary>SEC-A actor-id test on a parameter name (already lower-cased).</summary>
        internal static bool IsActorIdName(string lower)
        {
            if (!lower.EndsWith("id", StringComparison.Ordinal)) return false;
            foreach (var audit in AuditIdNames)
                if (lower == audit) return false;
            foreach (var tok in ActorIdTokens)
                if (lower.IndexOf(tok, StringComparison.Ordinal) >= 0) return true;
            return false;
        }
    }
}

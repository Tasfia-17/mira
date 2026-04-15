// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title MiraAuditLog
 * @notice Immutable on-chain audit trail for every MIRA agent decision.
 *
 * Every action MIRA takes — swap, alert, analysis, recommendation — is
 * anchored here as a cryptographically signed, timestamped, immutable record.
 *
 * This solves the AI agent trust problem: you can prove what MIRA did,
 * why she did it, and what the outcome was. Forever. On HashKey Chain.
 */
contract MiraAuditLog {

    // ── Types ────────────────────────────────────────────────────────────────

    enum ActionType {
        SWAP_EXECUTED,      // 0 — token swap via HyperIndex
        SWAP_QUOTED,        // 1 — swap quote shown to user
        ALERT_FIRED,        // 2 — proactive price alert sent
        PORTFOLIO_ANALYZED, // 3 — AI portfolio analysis
        RISK_FLAGGED,       // 4 — risk warning issued
        YIELD_RECOMMENDED,  // 5 — yield opportunity surfaced
        PAYMENT_CREATED,    // 6 — HSP payment link created
        STRATEGY_TRIGGERED  // 7 — autonomous strategy rule fired
    }

    struct AuditEntry {
        uint256 id;
        address wallet;       // user wallet this action relates to
        ActionType action;
        bytes32 dataHash;     // keccak256 of the full action payload (stored off-chain)
        string summary;       // human-readable one-liner (e.g. "Swapped 50 USDC → 23.7 HSK")
        uint256 timestamp;
        bool confirmed;       // did the user confirm this action?
        bytes32 txHash;       // on-chain tx hash if action produced a transaction
    }

    // ── State ────────────────────────────────────────────────────────────────

    uint256 public nextId = 1;

    // id → entry
    mapping(uint256 => AuditEntry) public entries;

    // wallet → list of entry ids
    mapping(address => uint256[]) public walletEntries;

    // authorized MIRA agent addresses (backend signers)
    mapping(address => bool) public authorizedAgents;

    address public owner;

    // ── Events ───────────────────────────────────────────────────────────────

    event ActionAnchored(
        uint256 indexed id,
        address indexed wallet,
        ActionType indexed action,
        string summary,
        uint256 timestamp
    );

    event ActionConfirmed(uint256 indexed id, bytes32 txHash);

    event AgentAuthorized(address indexed agent);
    event AgentRevoked(address indexed agent);

    // ── Modifiers ────────────────────────────────────────────────────────────

    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }

    modifier onlyAgent() {
        require(authorizedAgents[msg.sender], "not authorized agent");
        _;
    }

    // ── Constructor ──────────────────────────────────────────────────────────

    constructor() {
        owner = msg.sender;
        authorizedAgents[msg.sender] = true;
    }

    // ── Agent management ─────────────────────────────────────────────────────

    function authorizeAgent(address agent) external onlyOwner {
        authorizedAgents[agent] = true;
        emit AgentAuthorized(agent);
    }

    function revokeAgent(address agent) external onlyOwner {
        authorizedAgents[agent] = false;
        emit AgentRevoked(agent);
    }

    // ── Core: anchor an action ────────────────────────────────────────────────

    /**
     * @notice Anchor a MIRA decision on-chain.
     * @param wallet    The user wallet this action relates to
     * @param action    The type of action taken
     * @param dataHash  keccak256 of the full JSON payload (stored off-chain/IPFS)
     * @param summary   Human-readable summary for the audit dashboard
     * @return id       The audit entry ID
     */
    function anchor(
        address wallet,
        ActionType action,
        bytes32 dataHash,
        string calldata summary
    ) external onlyAgent returns (uint256 id) {
        id = nextId++;
        entries[id] = AuditEntry({
            id:        id,
            wallet:    wallet,
            action:    action,
            dataHash:  dataHash,
            summary:   summary,
            timestamp: block.timestamp,
            confirmed: false,
            txHash:    bytes32(0)
        });
        walletEntries[wallet].push(id);
        emit ActionAnchored(id, wallet, action, summary, block.timestamp);
    }

    /**
     * @notice Mark an anchored action as confirmed with its resulting tx hash.
     * Called after a swap or payment is confirmed on-chain.
     */
    function confirm(uint256 id, bytes32 txHash) external onlyAgent {
        AuditEntry storage e = entries[id];
        require(e.id == id, "entry not found");
        e.confirmed = true;
        e.txHash = txHash;
        emit ActionConfirmed(id, txHash);
    }

    // ── Read ─────────────────────────────────────────────────────────────────

    /// @notice Get all audit entry IDs for a wallet
    function getWalletEntries(address wallet) external view returns (uint256[] memory) {
        return walletEntries[wallet];
    }

    /// @notice Get the N most recent entries for a wallet
    function getRecentEntries(address wallet, uint256 n)
        external view returns (AuditEntry[] memory result)
    {
        uint256[] storage ids = walletEntries[wallet];
        uint256 count = ids.length < n ? ids.length : n;
        result = new AuditEntry[](count);
        for (uint256 i = 0; i < count; i++) {
            result[i] = entries[ids[ids.length - count + i]];
        }
    }

    /// @notice Verify a data hash matches an entry (proves MIRA's payload is authentic)
    function verify(uint256 id, bytes32 dataHash) external view returns (bool) {
        return entries[id].dataHash == dataHash;
    }
}

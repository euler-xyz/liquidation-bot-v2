// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.26;

import {ISwapper} from "./ISwapper.sol";
import {SwapVerifier} from "./SwapVerifier.sol";
import {IEVC} from "./IEVC.sol";

import {IERC4626, IERC20} from "./IEVault.sol";
import {IEVault} from "./IEVault.sol";
import {IBorrowing} from "./IEVault.sol";
import {ILiquidation} from "./IEVault.sol";

contract Liquidator {
    address public immutable owner;
    address public immutable swapperAddress;
    address public immutable swapVerifierAddress;
    address public immutable evcAddress;

    bytes32 public constant HANDLER_ONE_INCH = bytes32("1Inch");

    ISwapper swapper;
    IEVC evc;

    error Unauthorized();
    error LessThanExpectedCollateralReceived();

    constructor(address _owner, address _swapperAddress, address _swapVerifierAddress, address _evcAddress) {
        owner = _owner;
        swapperAddress = _swapperAddress;
        swapVerifierAddress = _swapVerifierAddress;
        evcAddress = _evcAddress;

        swapper = ISwapper(_swapperAddress);
        evc = IEVC(_evcAddress);
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Unauthorized");
        _;
    }

    struct LiquidationParams {
        address violatorAddress;
        address vault;
        address borrowedAsset;
        address collateralVault;
        address collateralAsset;
        uint256 repayAmount;
        uint256 seizedCollateralAmount;
        uint256 swapAmount;
        uint256 expectedRemainingCollateral;
        bytes swapData;
        address receiver;
    }

    event Liquidation(
        address indexed violatorAddress,
        address indexed vault,
        address repaidBorrowAsset,
        address seizedCollateralAsset,
        uint256 amountRepaid,
        uint256 amountCollaterallSeized
    );

    function liquidate_single_collateral(LiquidationParams calldata params) external returns (bool success) {
        bytes[] memory multicallItems = new bytes[](3);

        // Calls swap function of swapper which will swap some amount of seized collateral for borrowed asset
        // Swaps via 1inch
        multicallItems[0] = abi.encodeCall(
            ISwapper.swap,
            ISwapper.SwapParams({
                handler: HANDLER_ONE_INCH,
                mode: 0,
                account: address(0), // ignored
                tokenIn: params.collateralAsset,
                tokenOut: params.borrowedAsset,
                amountOut: 0,
                vaultIn: address(0), // ignored
                receiver: address(0), // ignored
                data: params.swapData
            })
        );

        // Use swapper contract to repay borrowed asset
        multicallItems[1] =
            abi.encodeCall(ISwapper.repay, (params.borrowedAsset, params.vault, params.repayAmount, address(this)));

        // Sweep any dust left in the swapper contract
        multicallItems[2] = abi.encodeCall(ISwapper.sweep, (params.borrowedAsset, 0, msg.sender));

        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](6);

        // Step 1: enable controller
        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableController, (address(this), params.vault))
        });

        // Step 2: enable collateral
        batchItems[1] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableCollateral, (address(this), params.collateralVault))
        });

        // Step 3: Liquidate account in violation
        batchItems[2] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                ILiquidation.liquidate,
                (params.violatorAddress, params.collateralVault, params.repayAmount, params.seizedCollateralAmount)
            )
        });

        // Step 4: Withdraw collateral from vault to swapper
        batchItems[3] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.collateralVault,
            value: 0,
            data: abi.encodeCall(IERC4626.withdraw, (params.swapAmount, swapperAddress, address(this)))
        });

        // Step 5: Swap collateral for borrowed asset, repay, and sweep overswapped borrow asset
        batchItems[4] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: swapperAddress,
            value: 0,
            data: abi.encodeCall(ISwapper.multicall, multicallItems)
        });

        // Step 6: withdraw remaining collateral
        batchItems[5] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.collateralVault,
            value: 0,
            data: abi.encodeCall(IERC4626.withdraw, (params.expectedRemainingCollateral, msg.sender, address(this)))
        });

        // Submit batch to EVC
        evc.batch(batchItems);

        emit Liquidation(
            params.violatorAddress,
            params.vault,
            params.borrowedAsset,
            params.collateralAsset,
            params.repayAmount,
            params.seizedCollateralAmount
        );

        return true;
    }

    // 2nd liquidation option: seize liquidated position without swapping/repaying, can only be done with existing collateral position
    function liquidateFromExistingCollateralPosition(LiquidationParams calldata params)
        external
        returns (bool success)
    {
        IEVC.BatchItem[] memory batchItems = new IEVC.BatchItem[](3);

        batchItems[0] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableController, (address(this), params.vault))
        });

        batchItems[1] = IEVC.BatchItem({
            onBehalfOfAccount: address(0),
            targetContract: address(evc),
            value: 0,
            data: abi.encodeCall(IEVC.enableCollateral, (address(this), params.collateralVault))
        });

        batchItems[2] = IEVC.BatchItem({
            onBehalfOfAccount: address(this),
            targetContract: params.vault,
            value: 0,
            data: abi.encodeCall(
                ILiquidation.liquidate,
                (params.violatorAddress, params.collateralVault, params.repayAmount, params.seizedCollateralAmount)
            )
        });

        evc.batch(batchItems);

        emit Liquidation(
            params.violatorAddress,
            params.vault,
            params.borrowedAsset,
            params.collateralAsset,
            params.repayAmount,
            params.seizedCollateralAmount
        );

        return true;
    }
}
